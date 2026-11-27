"""Normalise model-written math into the `$...$` LaTeX format the renderer expects.

Models sometimes ignore the LaTeX instruction and write ASCII math (`2 pi sqrt(m/k)`, `kg m^-3`,
`3.0 x 10^-5`), use `\\(..\\)` delimiters, or leak ANSI colour codes. `normalize_math` fixes
these deterministically; text already inside `$...$` is left alone.
"""
from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b")
_MATH = re.compile(r"(\$\$.+?\$\$|\$.+?\$)", re.S)
_ENV = re.compile(r"\\begin\{(align\*?|aligned|equation\*?|gather\*?|cases|array)\}.+?\\end\{\1\}", re.S)

_GREEK = ("alpha beta gamma delta epsilon theta lambda mu nu rho sigma tau phi omega eta "
          "Delta Gamma Lambda Omega Phi Sigma Theta pi").split()
_FUNCS = "arcsin arccos arctan sin cos tan sec csc cot log ln exp".split()
_UNITS = "mol kg cm mm km nm Pa Hz eV uF m s g K C L J N W V h".split()
_U = "(?:" + "|".join(_UNITS) + r")(?:\^\(?[+-]?\d+\)?)?"
# unit sequence, e.g. "kg m^-3", "m/s^2", "J mol^-1 K^-1"
_UNITSEQ = re.compile(r"(?<![\w(/^\\])(" + _U + r"(?:(?:\s+|\s*/\s*)" + _U + r")*)(?![\w(^])")
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|×|\*)\s*10\s*\^\s*\(?\s*([+-]?\d+)(?:\s*\))?")
_UF = re.compile(r"(\d)\s*u(F|C|A|V|J|m|s|g|H)\b")

_STRONG = re.compile(
    r"\^|sqrt\(|(?<![\\\w])(?:" + "|".join(_GREEK) + r")(?![A-Za-z])|[A-Za-z0-9]_[A-Za-z0-9({]"
    r"|[\w)]\*[\w(]|<=>|->|<=|>=|\\[a-zA-Z]+|(?<![A-Za-z])(?:" + "|".join(_FUNCS) + r")\(")
_LIGHT = re.compile(r"[-+]?\(?\d+(?:\.\d+)?\)?|[b-zB-HJ-Z]|[-+=/×<>]|[()\[\]|]")
_PUNCT = ".,;:?!"


def _balanced(s: str, i: int) -> int:
    """Index of the bracket closing the one at s[i], or -1."""
    depth = 0
    for j in range(i, len(s)):
        depth += s[j] == "("
        depth -= s[j] == ")"
        if depth == 0:
            return j
    return -1


def _brace_groups(t: str) -> str:
    """sqrt(x) -> \\sqrt{x}; ^(x) -> ^{x}; _(x) -> _{x}."""
    out, i = [], 0
    while i < len(t):
        for head, rep in (("sqrt(", "\\sqrt{"), ("^(", "^{"), ("_(", "_{")):
            if t.startswith(head, i):
                j = _balanced(t, i + len(head) - 1)
                if j != -1:
                    out.append(rep + _brace_groups(t[i + len(head):j]) + "}")
                    i = j + 1
                    break
        else:
            out.append(t[i])
            i += 1
    return "".join(out)


def _to_latex(t: str) -> str:
    t = t.replace("<=>", r"\Leftrightarrow ").replace("->", r"\to ")
    t = t.replace("<=", r"\le ").replace(">=", r"\ge ")
    t = _brace_groups(t)
    t = re.sub(r"\^([+-]?\d+(?:\.\d+)?|[A-Za-z])", r"^{\1}", t)
    t = re.sub(r"_([A-Za-z0-9]{2,})", r"_{\1}", t)
    t = re.sub(r"(?<![\\A-Za-z])arc(sin|cos|tan)(?![a-z])", r"\\\1^{-1}", t)
    t = re.sub(r"(?<![\\A-Za-z])(" + "|".join(_FUNCS[3:]) + r")(?![A-Za-z])", r"\\\1 ", t)
    t = re.sub(r"(?<![\\A-Za-z])(" + "|".join(_GREEK) + r")(?![A-Za-z])", r"\\\1 ", t)
    t = re.sub(r"(?<=[\w)}])\s*\*\s*(?=[\w(\\])", r" \\cdot ", t)
    t = re.sub(r"(?<=\d)\s+x\s+(?=\d)", r" \\times ", t)
    t = re.sub(r"\\(\w+) (?=[\^_}{)(\]\[,/+\-=]|$)", r"\\\1", t)
    return t.strip()


def _trim(span: str) -> tuple[str, str, str]:
    """Move trailing punctuation and unbalanced outer brackets out of a math span."""
    pre = post = ""
    while True:
        if span and span[-1] in _PUNCT:
            post = span[-1] + post; span = span[:-1]
        elif span.endswith(")") and span.count(")") > span.count("("):
            post = ")" + post; span = span[:-1]
        elif span.startswith("(") and span.count("(") > span.count(")"):
            pre += "("; span = span[1:]
        else:
            return pre, span, post


def _ascii_chunk(text: str) -> str:
    """Convert ASCII math in a chunk that contains no `$` math."""
    if not text.strip():
        return text
    text = _SCI.sub(lambda m: f"${m[1]}\\times10^{{{m[2]}}}$", text)
    text = _UF.sub(r"\1 $\\mu$\2", text)

    def unit(m: re.Match) -> str:
        seq = m[1]
        if "^" not in seq:
            return seq
        before = text[:m.start()].rstrip()
        if not (re.search(r"[\d)]$", before) or len(re.findall(r"[A-Za-z]+", seq)) > 1):
            return seq
        body = re.sub(r"\^\(?([+-]?\d+)\)?", r"^{\1}", seq)
        body = re.sub(r"\s+(?!/)", r"\\,", body.replace(" / ", "/"))
        return f"$\\mathrm{{{body}}}$"

    # unit sequences first; they create $...$ pieces the span pass then skips
    parts = []
    for is_math, piece in _split(text):
        parts.append(piece if is_math else _UNITSEQ.sub(unit, piece))
    text = "".join(parts)
    out = []
    for is_math, piece in _split(text):
        out.append(piece if is_math else _spans(piece))
    return "".join(out)


def _spans(text: str) -> str:
    toks = re.split(r"(\s+)", text)
    words = toks[::2]
    if not any(_STRONG.search(w) for w in words):
        return text

    def kind(w: str) -> str:
        if not w or "**" in w or re.fullmatch(r"_{2,}\W*", w) or "$" in w:
            return ""
        core = w.strip(_PUNCT)
        if _STRONG.search(core):
            return "S"
        if _LIGHT.fullmatch(core):
            return "L"
        # bracket/number fragments of a longer expression: "2))", "1)/x)", "(t"
        if re.fullmatch(r"[\w().+\-/=\[\]]+", core) and re.search(r"[()\d]", core) \
                and not re.search(r"[A-Za-z]{2,}", core):
            return "L"
        return ""

    kinds = [kind(w) for w in words]
    n, i, res = len(words), 0, []
    while i < n:
        if kinds[i] != "S":
            res.append((False, i, i)); i += 1; continue
        a = b = i
        while a > 0 and kinds[a - 1] and not words[a - 1].endswith(tuple(_PUNCT)):
            a -= 1
        while b + 1 < n and kinds[b + 1] and not words[b].endswith(tuple(_PUNCT)):
            b += 1
        # a span may not start/end on a bare operator
        while a < b and re.fullmatch(r"[-+=/×<>]", words[a]):
            a += 1
        while b > a and re.fullmatch(r"[-+=/×<>]", words[b]):
            b -= 1
        if res and res[-1][0] is False and res[-1][1] >= a:
            # already emitted plain tokens that belong to this span: drop them
            while res and not res[-1][0] and res[-1][1] >= a:
                res.pop()
        res.append((True, a, b)); i = b + 1
    out = []
    for is_m, a, b in res:
        seg = "".join(toks[2 * a: 2 * b + 1])
        if is_m:
            pre, body, post = _trim(seg)
            seg = f"{pre}${_to_latex(body)}${post}" if body else seg
        out.append(seg)
        if 2 * b + 1 < len(toks):
            out.append(toks[2 * b + 1])
    return "".join(out)


def _split(text: str) -> list[tuple[bool, str]]:
    out, pos = [], 0
    for m in _MATH.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


# KaTeX commands we may need to recover when a model mangles their backslash
_CMDS = sorted(set(_GREEK + [g.capitalize() for g in _GREEK] + _FUNCS + """
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi
    rho sigma tau upsilon phi varphi chi psi omega Upsilon Psi Xi
    circ text textbf mathrm mathbf mathcal mathit operatorname frac dfrac tfrac sqrt left right
    vec hat bar overline underline dot ddot times cdot div pm mp le leq ge geq ne neq approx propto
    sim equiv infty partial nabla int sum prod lim to rightarrow leftarrow Rightarrow Leftarrow
    longrightarrow rightleftharpoons parallel perp angle degree displaystyle quad qquad oplus
    boxed cup cap in notin subset subseteq ldots cdots big Big bigg mid ominus otimes therefore
    because odot rm""".split()), key=len, reverse=True)
_CMD_RE = "(?:" + "|".join(_CMDS) + r")(?![A-Za-z])"
# real \n-commands; any other "\n<letters>" is a newline the model escaped twice
# (written without their leading "n", since the pattern has already consumed "\\n")
_NCMDS = r"(?:e|eq|abla|u|i|ot|otin|ewline|leq|geq|less|gtr|mid|parallel|sim|cong" \
         r"|exists|Rightarrow|Leftarrow|Leftrightarrow|rightarrow|leftarrow|subseteq|supseteq)(?![A-Za-z])"


def repair_escapes(t: str) -> str:
    """Undo escape damage: ANSI codes, control chars standing in for a backslash, literal \\n,
    doubled backslashes before commands."""
    t = _ANSI.sub("", t)
    # a control char (often + stray "24"/"4" from a broken \u0024) where a backslash belonged
    t = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f](?:0?24|4)?(?=" + _CMD_RE + ")", r"\\", t)
    t = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f](?:0?24(?=[A-Za-z]))?", "", t)
    # earlier normaliser wrapped "\nWord" in math: "$smog.\nI$" -> "smog.\nI"
    t = re.sub(r"(?<=\$)\$([.,;:]?)\\n(?!" + _NCMDS + r")([A-Za-z]+)\$", r"\1\n\2", t)
    t = re.sub(r"(?<!\$)\$([A-Za-z]*[.,;:]?)\\n(?!" + _NCMDS + r")([A-Za-z]+)\$", r"\1\n\2", t)
    t = re.sub(r"\\n(?!" + _NCMDS + ")", "\n", t)
    # "60^\\circ" -> "60^\circ" (keep "\\" row breaks inside environments)
    t = re.sub(r"(?<![\\&])\\\\(?=" + _CMD_RE + ")", r"\\", t) if "\\begin" not in t else t
    return t


def normalize_math(text: str) -> str:
    if not text:
        return text
    t = repair_escapes(text)
    t = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", t, flags=re.S)
    t = re.sub(r"\\\((.+?)\\\)", r"$\1$", t, flags=re.S)
    # bare environments outside math -> display math
    out = []
    for is_math, piece in _split(t):
        out.append(piece if is_math else _ENV.sub(lambda m: f"$${m[0]}$$", piece))
    t = "".join(out)
    out = []
    for is_math, piece in _split(t):
        if is_math:
            out.append(piece); continue
        lines = []
        for ln in piece.split("\n"):
            ln = re.sub(r"\s*\\\\\s*$", "", ln)     # LaTeX "\\" line break left in plain text
            # markdown table rows: convert cell by cell
            if ln.lstrip().startswith("|"):
                lines.append("|".join(_ascii_chunk(c) for c in ln.split("|")))
            else:
                lines.append(_ascii_chunk(ln))
        out.append("\n".join(lines))
    return "".join(out)
