from collections import defaultdict
from itertools import combinations

from smartdoc.ncm.candidates import normalized
from smartdoc.ncm.contracts import Concept, DuplicateSuggestion, Mention
from smartdoc.nlp.contracts import LinguisticToken

MAX_SUGGESTIONS = 200


def with_lemmas(mentions: list[Mention], tokens: list[LinguisticToken]) -> list[Mention]:
    if not any(token.lemma for token in tokens):
        return mentions
    result = []
    for item in mentions:
        source = item.evidence.source
        parts = [
            token
            for token in tokens
            if source.start <= token.span.start and token.span.end <= source.end
        ]
        if parts and parts[0].span.start == source.start and parts[-1].span.end == source.end:
            form = normalized(" ".join(token.lemma or token.span.text for token in parts))
            item = item.model_copy(update={"lemma_form": form})
        result.append(item)
    return result


def signature(value: str) -> str:
    parts = value.replace("-", " ").split()
    if len(parts) < 2 or any(not item.isalpha() for item in parts):
        return ""
    last = parts[-1]
    if len(last) > 4 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
        parts[-1] = last[:-1]
    return " ".join(parts)


def duplicate_suggestions(concepts: list[Concept]) -> list[DuplicateSuggestion]:
    groups = defaultdict(dict)
    for concept in concepts:
        for item in concept.mentions:
            context = item.section_id or item.evidence.source.unit
            keys = {signature(concept.normalized), signature(item.lemma_form or "")}
            for key in sorted(keys - {""}):
                groups[(context, key)].setdefault(concept.id, (concept, item.evidence))
    suggestions = {}
    for (_, key), group in groups.items():
        # A large group has little resolving power.
        if len(group) > 24:
            continue
        for left, right in combinations(sorted(group), 2):
            first, first_evidence = group[left]
            second, second_evidence = group[right]
            if first.normalized == second.normalized or first.sense or second.sense:
                continue
            if first.category != second.category and "concept" not in {
                first.category,
                second.category,
            }:
                continue
            suggestions.setdefault(
                (left, right),
                DuplicateSuggestion(
                    left_id=left,
                    right_id=right,
                    lexical_key=key,
                    evidence=[first_evidence, second_evidence],
                ),
            )
            if len(suggestions) >= MAX_SUGGESTIONS:
                return list(suggestions.values())
    return list(suggestions.values())
