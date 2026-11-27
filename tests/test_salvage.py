import json

from agents.author import salvage
from core.llm import close_truncated_json
from core.models import DraftQuestion, Slot

SLOT = Slot(qno=1, section="Physics", chapter="Kinematics")
FULL = {"stem": "A ball is thrown up at $10$ m/s. Max height?", "options": ["5 m", "10 m", "2 m", "20 m"],
        "option_smiles": None, "answer": "A", "figure": None, "difficulty_estimate": 2,
        "working": "$h = v^2/2g = 100/20 = 5$ m. Long text continues here", "distractor_notes": "B: forgot 2"}


def cut_inside(field: str, n: int = 10) -> str:
    s = json.dumps(FULL)
    i = s.index(json.dumps(FULL[field])) + n
    return s[:i]


def test_complete_object_parses():
    assert close_truncated_json(json.dumps(FULL)) == FULL


def test_cut_in_working_is_salvaged():
    obj = close_truncated_json(cut_inside("working"))
    q = salvage(obj, SLOT)
    assert isinstance(q, DraftQuestion) and q.answer == "A" and q.working.startswith("$h")
    assert q.distractor_notes == ""


def test_cut_in_stem_is_rejected():
    assert salvage(close_truncated_json(cut_inside("stem")), SLOT) is None


def test_cut_before_working_is_rejected():
    s = json.dumps(FULL)
    assert salvage(close_truncated_json(s[:s.index('"working"')]), SLOT) is None


def test_trailing_backslash_in_latex():
    s = cut_inside("working", 4)
    s = s[:s.rindex("$") + 1] + "\\\\fr"  # ends mid-escape sequence
    assert salvage(close_truncated_json(s + "\\"), SLOT) is not None


def test_figure_required_slot_needs_figure():
    slot = Slot(qno=2, section="Physics", chapter="Optics", needs_figure=True, figure_kind="diagram")
    assert salvage(close_truncated_json(cut_inside("working")), slot) is None


def test_batch_keeps_complete_questions():
    s = json.dumps({"questions": [FULL, FULL, FULL]})
    obj = close_truncated_json(s[: len(s) - 60])
    qs = [salvage(x, SLOT) for x in obj["questions"]]
    assert sum(q is not None for q in qs) >= 2


def test_garbage():
    assert close_truncated_json("sorry, I cannot") is None
