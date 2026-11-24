import re
from dataclasses import dataclass
from typing import Literal

from smartdoc.retrieval.ranking import tokens

Intent = Literal["direct", "dependency", "relationship", "comparison", "timeline"]
SECTION = re.compile(r'(.+?) in section ["“]?([^?"”]+)["”]?\??', re.IGNORECASE)
PAIR_PATTERNS: tuple[tuple[Intent, str], ...] = (
    ("dependency", r"(?:how does|does) (.+?) depend(?: directly or indirectly)? on (.+)"),
    ("relationship", r"how (?:are|is) (.+?) and (.+?) (?:connected|related)"),
    (
        "comparison",
        r"(?:compare|what is the difference between) (.+?) (?:and|with|versus|vs\.?) (.+)",
    ),
    (
        "timeline",
        r"(?:which|what) was (introduced|published|released|approved) first[:,]? (.+?) or (.+)",
    ),
)


@dataclass(frozen=True)
class QuestionPlan:
    intent: Intent
    text: str
    section: str = ""
    concepts: tuple[str, ...] = ()
    action: str = ""


def plan_question(question: str) -> QuestionPlan:
    normalized = " ".join(question.split()).rstrip("?.!")
    qualified = SECTION.fullmatch(normalized)
    section = " ".join(tokens(qualified[2])) if qualified else ""
    prompt = qualified[1] if qualified else normalized
    for intent, pattern in PAIR_PATTERNS:
        if match := re.fullmatch(pattern, prompt, flags=re.IGNORECASE):
            if intent == "timeline":
                return QuestionPlan(intent, prompt, section, match.groups()[1:], match[1].lower())
            return QuestionPlan(intent, prompt, section, match.groups())
    return QuestionPlan("direct", prompt, section)
