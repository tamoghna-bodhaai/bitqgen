"""Thin OpenRouter client driven by config/models.yaml.

    from core.llm import LLM
    llm = LLM()                       # active profile
    res = llm.call("solver", messages, schema=SolverVerdict)   # -> CallResult
    res.data (parsed pydantic obj or None), res.text, res.model, res.cost

Each stage resolves to {model, fallbacks, reasoning, max_tokens}. A `model=` override
lets experiments (e.g. the solver test) try arbitrary models with the same plumbing.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Type

import yaml
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "models.yaml"


class FatalLLMError(RuntimeError):
    """Auth / credit / key-limit problems: retrying cannot help, so the job should stop."""


def _fatal(e: APIStatusError) -> bool:
    return e.status_code in (401, 402) or (e.status_code == 403 and "limit" in str(e.message).lower())


@dataclass
class CallResult:
    text: str
    data: Any = None
    model: str = ""
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: Optional[str] = None
    finish_reason: str = ""          # "length" = output cut off at max_tokens
    raw: dict = field(default_factory=dict, repr=False)


def image_part(path: str | Path) -> dict:
    """An OpenAI-style image content part from a local PNG/JPEG."""
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _resolve_profile(cfg: dict, name: str) -> dict:
    prof = cfg["profiles"][name]
    if "inherit" not in prof:
        return prof
    base = {k: dict(v) for k, v in _resolve_profile(cfg, prof["inherit"]).items()}
    for stage, ov in (prof.get("overrides") or {}).items():
        base.setdefault(stage, {}).update(ov)
    return base


class LLM:
    def __init__(self, profile: str | None = None, config: Path = CONFIG):
        load_dotenv(ROOT / ".env")
        self.cfg = yaml.safe_load(Path(config).read_text())
        self.profile_name = profile or self.cfg["active_profile"]
        self.stages = _resolve_profile(self.cfg, self.profile_name)
        key = os.environ.get(self.cfg["api_key_env"])
        if not key:
            raise RuntimeError(f"{self.cfg['api_key_env']} is not set (expected in .env)")
        self.client = OpenAI(base_url=self.cfg["base_url"], api_key=key, timeout=600, max_retries=2)
        self._lock = threading.Lock()
        self.total_cost = 0.0
        self.stats: dict[str, dict] = {}   # per-stage calls / cost / tokens / truncations

    def record(self, stage: str, cost: float = 0.0, prompt_tokens: int = 0, completion_tokens: int = 0,
               finish_reason: str = "", **counters: int) -> None:
        with self._lock:
            self.total_cost += cost
            s = self.stats.setdefault(stage, {"calls": 0, "cost": 0.0, "prompt_tokens": 0,
                                              "completion_tokens": 0, "truncated": 0})
            if cost or prompt_tokens or completion_tokens or finish_reason:
                s["calls"] += 1
            s["cost"] = round(s["cost"] + cost, 5)
            s["prompt_tokens"] += prompt_tokens
            s["completion_tokens"] += completion_tokens
            s["truncated"] += finish_reason == "length"
            for k, v in counters.items():
                s[k] = s.get(k, 0) + v

    def stage(self, name: str) -> dict:
        return self.stages[name]

    def call(self, stage: str, messages: list[dict], *, schema: Type[BaseModel] | None = None,
             model: str | None = None, reasoning: str | None = None, max_tokens: int | None = None,
             fallbacks: list[str] | None = None, attempts: int = 3) -> CallResult:
        st = self.stages.get(stage, {})
        model = model or st["model"]
        fb = fallbacks if fallbacks is not None else ([] if model != st.get("model") else st.get("fallbacks", []))
        body: dict[str, Any] = {"usage": {"include": True}}
        eff = reasoning or st.get("reasoning")
        if eff:
            body["reasoning"] = {"effort": eff}
        if fb:
            body["models"] = [model, *fb]  # OpenRouter tries these in order
        kwargs: dict[str, Any] = {}
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True,
                                "schema": _strict_schema(schema.model_json_schema())},
            }
        last_err = None
        for i in range(attempts):
            try:
                resp = self.client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens or st.get("max_tokens", 8000),
                    extra_body=body, **kwargs)
            except (RateLimitError, APIConnectionError) as e:
                last_err = repr(e)
                time.sleep(2 ** i * 3)
                continue
            except APIStatusError as e:
                last_err = f"{e.status_code}: {e.message}"
                if _fatal(e):
                    raise FatalLLMError(f"OpenRouter refused the request ({e.status_code}): {str(e.message)[:200]}")
                if e.status_code >= 500:
                    time.sleep(2 ** i * 3)
                    continue
                return CallResult(text="", model=model, error=last_err)
            if not resp.choices:
                last_err = f"no choices: {getattr(resp, 'error', None)}"
                time.sleep(2)
                continue
            msg = resp.choices[0].message
            text = msg.content or ""
            usage = resp.usage
            cost = float((usage.model_extra or {}).get("cost") or 0) if usage else 0.0
            finish = resp.choices[0].finish_reason or ""
            res = CallResult(text=text, model=resp.model, cost=cost, finish_reason=finish,
                             prompt_tokens=usage.prompt_tokens if usage else 0,
                             completion_tokens=usage.completion_tokens if usage else 0)
            self.record(stage, cost, res.prompt_tokens, res.completion_tokens, finish)
            if schema is not None:
                try:
                    res.data = parse_schema(schema, text)
                except (ValidationError, ValueError) as e:
                    res.error = f"schema: {e}"[:500]
            return res
        return CallResult(text="", model=model, error=last_err)


PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "python_exec",
        "description": ("Run a short Python 3 script (numpy, sympy, math available) and return its stdout. "
                        "Use print() for results. Use it for arithmetic and algebra checks."),
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                       "required": ["code"], "additionalProperties": False},
    },
}


def _run_tool(name: str, args: str) -> str:
    from figures.runner import run_python  # local import: keeps core free of heavy deps
    try:
        code = json.loads(args or "{}").get("code", "")
    except json.JSONDecodeError:
        return "error: arguments were not valid JSON"
    if name != "python_exec" or not code:
        return "error: unknown tool or empty code"
    r = run_python(code, timeout=30, prelude=False)
    return (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "") or "(no output)"


def call_with_tools(llm: "LLM", stage: str, messages: list[dict], *, schema: Type[BaseModel],
                    max_turns: int = 6) -> CallResult:
    """Tool loop (python_exec) for stages configured with `tools`; final answer parsed into `schema`.
    Falls back to a plain structured call if the provider rejects tools."""
    st = llm.stages.get(stage, {})
    if "python_exec" not in (st.get("tools") or []):
        return llm.call(stage, messages, schema=schema)
    msgs = list(messages)
    msgs[-1] = dict(msgs[-1])
    hint = ("\n\nYou may call python_exec to check numerics. When done, reply with ONLY a JSON object "
            f"with keys: {', '.join(schema.model_fields)}.")
    if isinstance(msgs[-1]["content"], str):
        msgs[-1]["content"] += hint
    else:
        msgs[-1]["content"] = [*msgs[-1]["content"], {"type": "text", "text": hint}]
    body: dict[str, Any] = {"usage": {"include": True}}
    if st.get("reasoning"):
        body["reasoning"] = {"effort": st["reasoning"]}
    if st.get("fallbacks"):
        body["models"] = [st["model"], *st["fallbacks"]]
    cost = 0.0
    model = st["model"]
    for _ in range(max_turns):
        try:
            resp = llm.client.chat.completions.create(model=st["model"], messages=msgs, tools=[PYTHON_TOOL],
                                                      max_tokens=st.get("max_tokens", 8000), extra_body=body)
        except APIStatusError as e:
            if _fatal(e):
                raise FatalLLMError(f"OpenRouter refused the request ({e.status_code}): {str(e.message)[:200]}")
            if e.status_code in (400, 404):  # tools unsupported on this route: plain call
                return llm.call(stage, messages, schema=schema)
            return CallResult(text="", model=model, error=f"{e.status_code}: {e.message}", cost=cost)
        except (RateLimitError, APIConnectionError) as e:
            time.sleep(5)
            continue
        if not resp.choices:
            continue
        u = resp.usage
        c = float((u.model_extra or {}).get("cost") or 0) if u else 0.0
        cost += c
        llm.record(stage, c, u.prompt_tokens if u else 0, u.completion_tokens if u else 0,
                   resp.choices[0].finish_reason or "")
        model = resp.model
        msg = resp.choices[0].message
        if msg.tool_calls:
            msgs.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                msgs.append({"role": "tool", "tool_call_id": tc.id,
                             "content": _run_tool(tc.function.name, tc.function.arguments)[:6000]})
            continue
        text = msg.content or ""
        try:
            return CallResult(text=text, data=parse_schema(schema, text), model=model,
                              cost=cost)
        except (ValidationError, ValueError):
            msgs.append({"role": "assistant", "content": text})
            msgs.append({"role": "user", "content": "Now output only the final JSON object."})
            res = llm.call(stage, msgs, schema=schema)
            res.cost += cost
            return res
    res = llm.call(stage, messages, schema=schema)
    res.cost += cost
    return res


import re as _re

# A single backslash before t/r/b/f/n in JSON is a valid escape, so "\text" arrives as TAB+"ext".
# Restore LaTeX commands that were swallowed that way.
_CTRL = {"\t": "t", "\r": "r", "\b": "b", "\f": "f"}
_NL_CMDS = r"(?:eq|eg|abla|ot|u|e|i|ewline|leq|geq|parallel|sim|mid|exists|ormalsize|cong|ewcommand)(?![a-z])"


_TEXT_KEYS = {"stem", "options", "solution", "text"}


def _norm(key, v):
    """ASCII-math -> LaTeX for printed text fields only (never code or briefs)."""
    from core.mathfix import normalize_math
    if key not in _TEXT_KEYS:
        return v
    if isinstance(v, str):
        return normalize_math(v)
    if isinstance(v, list):
        return [normalize_math(x) if isinstance(x, str) else x for x in v]
    return v


def repair_latex(v):
    if isinstance(v, str):
        for ch, letter in _CTRL.items():
            v = _re.sub(_re.escape(ch) + r"(?=[A-Za-z])", lambda m, L=letter: "\\" + L, v)
        return _re.sub(r"\n(?=" + _NL_CMDS + ")", lambda m: "\\n", v)
    if isinstance(v, list):
        return [repair_latex(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(k, repair_latex(x)) for k, x in v.items()}
    return v


def parse_schema(schema, text: str):
    return schema.model_validate(repair_latex(json.loads(_extract_json(text))))


def close_truncated_json(text: str):
    """Best-effort parse of a JSON object cut off mid-output (finish_reason == "length").

    Tries closing the open string/brackets at the cut; failing that, backs off to the last comma
    outside a string. Returns the parsed dict (partial) or None."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
    start = t.find("{")
    if start == -1:
        return None
    t = t[start:]
    stack: list[str] = []
    in_str = esc = False
    cuts: list[tuple[int, str]] = []   # (position of a top-level-safe comma, closers at that point)
    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                try:
                    return json.loads(t[:i + 1])
                except json.JSONDecodeError:
                    return None
        elif ch == ",":
            cuts.append((i, "".join(reversed(stack))))
    closers = "".join(reversed(stack))
    head = t[:-1] if (in_str and esc) else t
    cands = [head + ('"' if in_str else "") + closers]
    cands += [t[:pos] + cl for pos, cl in reversed(cuts)]
    for c in cands[:40]:
        try:
            v = json.loads(c)
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("no JSON object in response")
    return t[s:e + 1]


def _strict_schema(schema: dict) -> dict:
    """OpenAI-style strict mode: every object lists all props as required, no extras."""
    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    schema = json.loads(json.dumps(schema))
    fix(schema)
    return schema
