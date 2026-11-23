import re
import unicodedata
from collections.abc import Callable
from datetime import date, time
from functools import cache

from smartdoc.nlp.contracts import LinguisticToken, NamedSpan, TemporalSpan, TextSpan

Span = Callable[[int, int], TextSpan]
TOKEN = re.compile(r"\d+(?:[.,]\d+)+|[^\W\d_][\w]*(?:[’'\-][^\W_]+)*|\d+|[^\w\s]|_", re.UNICODE)
STOP = frozenset("the a an and or is are was were to for of with in from this these it by".split())
SIGNALS = STOP | {"uses", "requires", "measures", "depends", "can", "must"}
BOUNDARY = re.compile(r"""[.!?。！？]+["'”’)]*(?=\s|$)""")
ABBREVIATION = re.compile(r"(?:\b(?:Mr|Mrs|Dr|Fig|Eq|No|vs|etc)|\b(?:[A-Za-z]\.)[A-Za-z])\.$", re.I)
MONTHS = (
    "January February March April May June July August September October November December".split()
)
MONTH_MAP = {label.lower(): index for index, label in enumerate(MONTHS, 1)}
ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
CALENDAR = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
CLOCK = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
RELATIVE = re.compile(
    r"\b(?:today|yesterday|tomorrow|(?:last|next|this)\s+(?:week|month|year))\b", re.I
)
MEASUREMENT = re.compile(
    r"(?<![\w.])[-+−]?\d+(?:\.\d+)?\s*(?:°[CF]|kPa|MPa|Pa|kW|MW|W|kWh|Wh|"
    r"mm|cm|km|mg|kg|mL|Hz|kHz|MHz|GHz|µm|μm|rpm|ms|V|A|%|Ω)(?!\w)"
)
TECHNOLOGY = ("Python", "JavaScript", "TypeScript", "SQL", "SQLite", "HTTP", "HTTPS", "ONNX")


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def is_english_script(text: str) -> bool:
    letters = [character for character in text if character.isalpha()]
    return not letters or sum(
        "LATIN" in unicodedata.name(character, "") for character in letters
    ) >= 0.6 * len(letters)


def language(text: str) -> str:
    if not is_english_script(text):
        return "und"
    words = {normalized(value) for value in TOKEN.findall(text)}
    return "en" if len(words & SIGNALS) >= 2 else "und"


def sentences(text: str) -> list[tuple[int, int]]:
    ranges = []
    start = 0
    ends = [
        match.end()
        for match in BOUNDARY.finditer(text)
        if not ABBREVIATION.search(text[max(start, match.start() - 12) : match.start() + 1])
    ]
    for end in [*ends, len(text)]:
        piece = text[start:end]
        if piece.strip():
            ranges.append((start + len(piece) - len(piece.lstrip()), start + len(piece.rstrip())))
        start = end
    return ranges


def tokenize(text: str, anchor: Span) -> list[LinguisticToken]:
    return [
        LinguisticToken(span=anchor(match.start(), match.end()), normalized=normalized(match[0]))
        for match in TOKEN.finditer(text)
    ]


def temporal(text: str, anchor: Span) -> list[TemporalSpan]:
    found = []
    for pattern in (ISO, CALENDAR, CLOCK, RELATIVE):
        for match in pattern.finditer(text):
            kind = "date"
            try:
                if pattern is ISO:
                    value = date.fromisoformat(match[0]).isoformat()
                elif pattern is CALENDAR:
                    value = date(
                        int(match[3]), MONTH_MAP[match[1].lower()], int(match[2])
                    ).isoformat()
                elif pattern is CLOCK:
                    kind = "time"
                    value = time(int(match[1]), int(match[2])).isoformat(timespec="minutes")
                else:
                    kind = "relative"
                    value = None
            except ValueError:
                continue
            found.append(TemporalSpan(span=anchor(*match.span()), kind=kind, normalized=value))
    return sorted(found, key=lambda item: (item.span.start, item.span.end))


@cache
def term_pattern(terms: tuple[str, ...]) -> re.Pattern:
    alternatives = "|".join(map(re.escape, sorted(terms, key=len, reverse=True)))
    return re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)", re.I)


def entities(
    text: str,
    anchor: Span,
    dates: list[TemporalSpan],
    glossary: dict[str, list[str]],
) -> list[NamedSpan]:
    found = [
        NamedSpan(
            span=item.span, label="TIME" if item.kind == "time" else "DATE", method="temporal-rule"
        )
        for item in dates
    ]
    found.extend(
        NamedSpan(span=anchor(*match.span()), label="MEASUREMENT", method="quantity-rule")
        for match in MEASUREMENT.finditer(text)
    )
    for label, terms in {
        "TECHNOLOGY": [*TECHNOLOGY, *glossary.get("TECHNOLOGY", [])],
        **{label: terms for label, terms in glossary.items() if label != "TECHNOLOGY"},
    }.items():
        if terms:
            found.extend(
                NamedSpan(span=anchor(*match.span()), label=label, method="term-list")
                for match in term_pattern(tuple(terms)).finditer(text)
            )
    return found
