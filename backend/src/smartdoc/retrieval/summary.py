import re
from collections import Counter
from math import log1p

from smartdoc.retrieval.ranking import STOP, tokens
from smartdoc.structure.contracts import Chunk

SUMMARY_REQUEST = re.compile(
    r"(?:please )?(?:"
    r"summari[sz]e(?: (?:this|the|my) (?:document|pdf|file|notes))?"
    r"|(?:(?:give me|provide|write) (?:a |an )?)?(?:brief |short )?(?:summary|overview)"
    r"(?: of (?:this|the|my) (?:document|pdf|file|notes))?"
    r"|what is (?:this|the) (?:document|pdf|file) about"
    r")[.!?]?",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
SUMMARY_SIZE = 5
TEXT_ELEMENTS = {"paragraph", "list_item", "sentence", "caption", "table_row"}


def representative_excerpts(chunks: list[Chunk]) -> list[tuple[Chunk, str]]:
    candidates = []
    seen = set()
    for chunk in chunks:
        if chunk.element_type not in TEXT_ELEMENTS:
            continue
        for fragment in SENTENCE_BREAK.split(chunk.text):
            excerpt = fragment.strip()
            terms = frozenset(tokens(excerpt)) - STOP
            if len(terms) < 4 or not 30 <= len(excerpt) <= 480 or terms in seen:
                continue
            seen.add(terms)
            candidates.append((chunk, excerpt, terms))
    if not candidates:
        return []

    frequencies = Counter(word for _, _, terms in candidates for word in terms)
    selected = []
    units: Counter[int] = Counter()
    used_chunks = set()
    covered: set[str] = set()
    for _ in range(SUMMARY_SIZE):
        remaining = [
            (chunk, excerpt, terms)
            for chunk, excerpt, terms in candidates
            if chunk.id not in used_chunks and terms - covered
        ]
        if not remaining:
            break
        chunk, excerpt, terms = max(
            remaining,
            key=lambda item: (
                sum(log1p(frequencies[word]) for word in sorted(item[2]))
                / len(item[2])
                * len(item[2] - covered)
                / len(item[2])
                / (1 + units[item[0].primary.unit])
            ),
        )
        selected.append((chunk, excerpt))
        covered.update(terms)
        used_chunks.add(chunk.id)
        units[chunk.primary.unit] += 1
    return sorted(selected, key=lambda item: item[0].ordinal)
