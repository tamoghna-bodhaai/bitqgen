"""Mark past-paper questions whose key/text is doubtful as exemplar_ok=false in t*.json.

  uv run python -m ingest.flag_doubtful [paper_id ...]     (default: all papers)

They stay in the corpus (style stats, duplicate checks) but are never shown to authors as examples.
Rule: the transcriber's `notes` say the key is doubtful/wrong/ambiguous, or that stem/option text was
cut off, garbled, missing or reconstructed. Re-run after transcribing; then re-run ingest.merge.
"""
import json
import re
import sys

from ingest.layout import CORPUS

DOUBT = re.compile(
    r"doubtful|wrong|flawed|ambiguous|inconsistent|does not match|doesn't match|no real roots|ignores|"
    r"retained|both .* true|absent|none match|garbled|missing|omits the statements|identical|"
    r"same order|both print|cut off|cropped|truncated|reconstructed|partly|assumed|inferred|"
    r"approximat|guess|treat it as antonym|treat .* as|count non-zero|but .*key|key .* but|"
    r"biology question|duplicate of|depends on the sign|different convention|"
    r"used since|corresponds to|likely|questionable|not printed|misprint|printed key|read as|no solution", re.I)
# Reviewed by hand: notes that question the key/text without matching the keywords above.
MANUAL = {("2022", 8), ("2024s1", 75), ("2024s1", 94), ("2024s1", 98), ("2024s2", 72), ("2025s2", 31),
          ("2025s2", 105), ("2025s2", 119), ("2026s1", 52), ("2026s2", 77)}
BENIGN = re.compile(r"^(solution completed by transcriber;?\s*)$|source tag", re.I)


def doubtful(note: str) -> bool:
    n = re.sub(r"solution completed by transcriber;?\s*", "", note or "", flags=re.I)
    return bool(n.strip()) and not BENIGN.search(n) and bool(DOUBT.search(n))


def run(pids):
    total = 0
    for pid in pids:
        for f in sorted((CORPUS / pid).glob("t[0-9]*.json")):
            qs = json.loads(f.read_text())
            changed = False
            for q in qs:
                bad = doubtful(q.get("notes") or "") or (pid, q["qno"]) in MANUAL
                if bad and q.get("exemplar_ok", True):
                    q["exemplar_ok"] = False
                    changed = True
                total += bad
            if changed:
                f.write_text(json.dumps(qs, indent=1, ensure_ascii=False))
    print(f"{total} question(s) marked exemplar_ok=false")


if __name__ == "__main__":
    run(sys.argv[1:] or sorted(p.name for p in CORPUS.iterdir() if (p / "skeleton.json").exists()))
