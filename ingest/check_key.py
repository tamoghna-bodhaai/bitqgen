"""Cross-check skeleton answers against the answer-key table printed at the end of each PDF.

  uv run python -m ingest.check_key            # all papers in data/corpus
"""
import json

import pymupdf

from ingest.layout import CORPUS, ROOT


def key_table(pdf) -> dict[int, str]:
    doc = pymupdf.open(pdf)
    key: dict[int, str] = {}
    for page in list(doc)[-3:]:
        toks = page.get_text().split()
        mode, nums, i = None, [], 0
        for t in toks:
            if t.startswith("Que"):
                mode, nums = "q", []
            elif t.startswith("Ans"):
                mode, i = "a", 0
            elif mode == "q" and t.isdigit():
                nums.append(int(t))
            elif mode == "a" and t in ("A", "B", "C", "D") and i < len(nums):
                key[nums[i]] = t
                i += 1
    return key


def main() -> None:
    for d in sorted(CORPUS.iterdir()):
        sk = d / "skeleton.json"
        if not sk.exists():
            continue
        s = json.loads(sk.read_text())
        key = key_table(ROOT / "bitsat" / s["source_pdf"])
        diff = [(q["qno"], q["answer"], key.get(q["qno"])) for q in s["questions"]
                if q["qno"] in key and key[q["qno"]] != q["answer"]]
        print(f"{s['paper_id']:7s} questions={len(s['questions'])} key_table={len(key)} mismatches={diff}")


if __name__ == "__main__":
    main()
