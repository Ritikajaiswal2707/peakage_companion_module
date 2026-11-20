"""Loads course modules from content/modules/*.json.

To add or edit a module, edit its JSON file. No code change needed.
Modules are shown (and unlocked) in the order of their "order" field.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown as md

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content" / "modules"


@dataclass
class Question:
    id: str
    text: str
    options: list[str]
    answer: int
    explanation: str = ""


@dataclass
class Lesson:
    title: str
    body: str
    video_url: str = ""

    @property
    def html(self) -> str:
        return md.markdown(self.body, extensions=["tables", "sane_lists"])

    @property
    def video_embed(self) -> str:
        """YouTube links become embed URLs; anything else is returned as-is."""
        url = self.video_url.strip()
        if not url:
            return ""
        match = re.search(r"(?:youtu\.be/|v=|/embed/|/shorts/)([A-Za-z0-9_-]{11})", url)
        return f"https://www.youtube.com/embed/{match.group(1)}" if match else url


@dataclass
class Module:
    code: str
    order: int
    title: str
    track: str
    stage: str
    summary: str
    lessons: list[Lesson]
    questions: list[Question]
    pass_percent: int = 80
    questions_per_quiz: int = 5
    max_attempts: int = 2
    offline_note: str = ""
    question_map: dict[str, Question] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.question_map = {q.id: q for q in self.questions}


def _load_module(path: Path) -> Module:
    raw = json.loads(path.read_text(encoding="utf-8"))
    lessons = [Lesson(**lesson) for lesson in raw.pop("lessons")]
    questions = [Question(**q) for q in raw.pop("questions")]
    module = Module(lessons=lessons, questions=questions, **raw)

    problems = []
    if not lessons:
        problems.append("no lessons")
    if len(questions) < module.questions_per_quiz:
        problems.append(
            f"only {len(questions)} questions but questions_per_quiz is {module.questions_per_quiz}"
        )
    if len(module.question_map) != len(questions):
        problems.append("duplicate question ids")
    for q in questions:
        if not 0 <= q.answer < len(q.options):
            problems.append(f"question {q.id} answer index out of range")
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return module


def load_modules(directory: Path = CONTENT_DIR) -> list[Module]:
    modules = [_load_module(p) for p in sorted(directory.glob("*.json"))]
    codes = [m.code for m in modules]
    if len(set(codes)) != len(codes):
        raise ValueError("Two modules share the same code")
    return sorted(modules, key=lambda m: m.order)


MODULES: list[Module] = load_modules()
MODULE_BY_CODE: dict[str, Module] = {m.code: m for m in MODULES}


@dataclass
class OfflineStepDef:
    code: str
    title: str
    description: str


def load_offline_steps(path: Path = CONTENT_DIR.parent / "offline_steps.json") -> list[OfflineStepDef]:
    steps = [OfflineStepDef(**s) for s in json.loads(path.read_text(encoding="utf-8"))]
    if len({s.code for s in steps}) != len(steps):
        raise ValueError("offline_steps.json: duplicate step codes")
    return steps


OFFLINE_STEPS: list[OfflineStepDef] = load_offline_steps()
OFFLINE_STEP_BY_CODE: dict[str, OfflineStepDef] = {s.code: s for s in OFFLINE_STEPS}
