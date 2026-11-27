"""Canonical data model. `Paper` JSON is the single source of truth for rendering/export."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Letter = Literal["A", "B", "C", "D"]
LETTERS: tuple[Letter, ...] = ("A", "B", "C", "D")

FigureKind = Literal[
    "circuit", "diagram", "plot", "chem", "lr", "image", "none"
]


class Figure(BaseModel):
    """A rendered figure. `path` is relative to the paper's asset directory."""
    kind: FigureKind = "image"
    path: str
    width_pct: int = Field(70, ge=10, le=100, description="Width as % of column")
    caption: Optional[str] = None


class FigureSpec(BaseModel):
    """What the author asks the figure agent to draw (before rendering)."""
    kind: FigureKind
    description: str
    params: dict = Field(default_factory=dict)


class Option(BaseModel):
    text: str  # Markdown + inline LaTeX ($...$)
    figure: Optional[Figure] = None
    alt: Optional[str] = None  # text description of `figure` (not rendered)


class Question(BaseModel):
    qno: int
    section: str
    stem: str  # Markdown + LaTeX ($...$ inline, $$...$$ display)
    figure: Optional[Figure] = None
    options: list[Option] = Field(min_length=4, max_length=4)
    answer: Letter
    solution: str = ""
    solution_figure: Optional[Figure] = None
    source_tag: Optional[str] = None  # e.g. "[2019 : 12 Jan Shift 2]"

    # metadata (not rendered)
    chapter: Optional[str] = None
    subtopic: Optional[str] = None
    archetype: Optional[str] = None
    difficulty: Optional[int] = Field(None, ge=1, le=5)
    figure_kind: Optional[FigureKind] = None
    passage_id: Optional[str] = None
    notes: Optional[str] = None
    exemplar_ok: bool = True  # False: doubtful key/text in the source — never shown to authors as an example


class SectionSpec(BaseModel):
    name: str
    count: int


class Pattern(BaseModel):
    id: str
    title: str
    sections: list[SectionSpec]
    marks_correct: int = 3
    marks_wrong: int = -1
    duration_min: int = 180

    @property
    def total(self) -> int:
        return sum(s.count for s in self.sections)

    def section_ranges(self) -> list[tuple[str, int, int]]:
        out, start = [], 1
        for s in self.sections:
            out.append((s.name, start, start + s.count - 1))
            start += s.count
        return out


class Paper(BaseModel):
    title: str = "BITSAT Practice Paper"
    subtitle: Optional[str] = None
    pattern_id: str = "bitsat_130"
    questions: list[Question]

    def sorted(self) -> list[Question]:
        return sorted(self.questions, key=lambda q: q.qno)


# ---------------------------------------------------------------- generation pipeline

class Slot(BaseModel):
    """One blueprint row: what a single generated question should be."""
    qno: int
    section: str
    chapter: str
    subtopic: str = ""
    archetype: str = ""
    brief: str = ""                     # planner's one-line angle for the author
    difficulty: int = 2
    needs_figure: bool = False
    figure_kind: Optional[FigureKind] = None
    lr_generator: Optional[str] = None  # deterministic non-verbal LR generator name
    passage_id: Optional[str] = None    # English RC groups share a passage
    exemplar_ids: list[str] = Field(default_factory=list)  # "<paper>:<qno>"


class Blueprint(BaseModel):
    pattern_id: str
    slots: list[Slot]


# LLM-facing schemas: no numeric/length constraints (strict json_schema portability);
# they are validated in code instead.

class FigureRequest(BaseModel):
    kind: Literal["circuit", "diagram", "plot", "chem"]
    description: str = Field(description="Precise drawing brief: every label, value, arrow and "
                                         "relative position needed. Never reveal the answer.")
    smiles: Optional[str] = Field(None, description="kind=chem only: SMILES of the structure "
                                  "(use '>>' for a reaction scheme, e.g. 'CCO>>CC=O').")


class DraftQuestion(BaseModel):
    # Field order matters: short, essential fields first so that an output cut off at max_tokens
    # still carries a complete question (see agents.author.salvage). Long text goes last.
    stem: str = Field(description="Question text. Markdown + LaTeX ($...$ inline, $$...$$ display).")
    options: list[str] = Field(description="Exactly 4 option texts, without (A)-(D) labels.")
    option_smiles: Optional[list[str]] = Field(
        None, description="Only when the 4 options are chemical structures: 4 SMILES strings "
                          "(the options' text then becomes a short name or empty).")
    answer: Literal["A", "B", "C", "D"]
    figure: Optional[FigureRequest] = None
    difficulty_estimate: int = Field(description="1 (direct) to 5 (very hard)")
    working: str = Field(description="Concise solution proving the key: key equations and numbers only, "
                                     "at most ~8 lines. No restating the question, no prose padding.")
    distractor_notes: str = Field(description="One short line per wrong option: which mistake it encodes.")

    @field_validator("option_smiles", mode="before")
    @classmethod
    def _blank_smiles_to_none(cls, v):
        # Strict-schema models (DeepSeek) fill this optional field with [] or ["", "", "", ""] on
        # questions without structures; treat that as "not used" instead of failing lint.
        if isinstance(v, list) and not any(str(x or "").strip() for x in v):
            return None
        return v


class DraftBatch(BaseModel):
    questions: list[DraftQuestion] = Field(description="One question per brief, in the same order.")


class SolverVerdict(BaseModel):
    working: str = Field(description="Key steps (max ~8 lines)")
    answer: Literal["A", "B", "C", "D", "NONE"] = Field(
        description="The single correct option, or NONE if no option is correct")
    confidence: float = Field(description="0 to 1")
    multiple_correct: bool = Field(description="True if more than one option is defensible")
    issues: list[str] = Field(description="Ambiguities, missing data, unit or typo problems; empty if none")
    difficulty: int = Field(description="1 (direct) to 5 (very hard), relative to JEE Main")


class FigureVerdict(BaseModel):
    ok: bool
    problems: list[str] = Field(description="Concrete defects: missing/wrong labels, clutter, "
                                            "answer leaked, mismatch with the text. Empty if ok.")


class CriticItem(BaseModel):
    qno: int
    severity: Literal["minor", "major"]
    problem: str


class CriticReport(BaseModel):
    items: list[CriticItem]
    summary: str


class SolutionText(BaseModel):
    solution: str


class TranscribedQ(BaseModel):
    """One past-paper question read off a page-column image (same fields as data/corpus/*/t*.json)."""
    qno: int
    stem: str = Field(description="Question text, Markdown + LaTeX ($...$ inline, $$...$$ display). "
                                  "No question number.")
    options: list[str] = Field(description="Exactly 4 option texts without (A)-(D) labels; "
                                           "an empty string when the option is only a drawing.")
    solution: str = Field(description="The printed solution, transcribed (LaTeX). Empty if not visible.")
    chapter: str = Field(description="Chapter / question type, preferably one of the given names")
    subtopic: str
    archetype: str = Field(description="Short phrase naming the problem pattern")
    difficulty: int = Field(description="1 (direct) to 5 (very hard)")
    figure_kind: Optional[Literal["diagram", "circuit", "plot", "chem", "table", "image"]] = None
    passage_id: Optional[str] = Field(None, description="Shared id for questions on the same passage")
    stem_figure_transcribed: bool = Field(False, description="True if a stem drawing (e.g. a table) "
                                          "was fully rewritten as text in the stem")
    notes: str = Field("", description="Anything doubtful: cut-off text, illegible parts, key looks wrong. "
                                       "Empty if clean.")


class TranscriptionBatch(BaseModel):
    questions: list[TranscribedQ]
