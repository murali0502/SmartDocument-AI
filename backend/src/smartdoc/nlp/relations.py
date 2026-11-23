import re

from smartdoc.nlp.contracts import (
    CoreferenceCandidate,
    LinguisticToken,
    NamedSpan,
    PredicateFrame,
    RelationCandidate,
    Role,
    TextSpan,
)
from smartdoc.nlp.lexical import TOKEN, Span

PREDICATES = {
    "DEPENDS_ON": r"depend(?:s)? on",
    "REQUIRES": r"require(?:s)?",
    "USES": r"use(?:s)?",
    "PRODUCES": r"produce(?:s)?",
    "MEASURES": r"measure(?:s)?",
    "HAS_PART": r"consist(?:s)? of|contain(?:s)?",
    "DEFINED_BY": r"is defined as|means",
    "LEADS_TO": r"lead(?:s)? to|cause(?:s)?",
    "SUPPORTS": r"support(?:s)?",
}
PREDICATE = "(?:" + "|".join(PREDICATES.values()) + ")"
PATTERN = re.compile(
    r"(?P<subject>[\w][\w /+μ°'’-]*?)\s+"
    r"(?:(?P<modality>must|may|might|can|could|should|would|will)\s+)?"
    r"(?:(?:does|do|did)\s+)?"
    r"(?:(?P<negation>not|never|cannot|(?:does|do|did|ca|could|must|should|would|wo)n['’]t)\s+)?"
    rf"(?P<predicate>{PREDICATE})\s+"
    r"(?P<object>[^\n.!?;]+?)\s*[.!?]?\s*$",
    re.I,
)
UNSAFE_CLAUSE = re.compile(
    r"[,;:]|\b(?:and|or|but|because|while|although|unless|if|when|then|where|however|than|that|"
    r"who|whether|no|neither|without|except|says?|claims?|believes?|suggests?)\b",
    re.I,
)
MODAL_NEGATION = {
    "cannot": "can",
    "can't": "can",
    "couldn't": "could",
    "mustn't": "must",
    "shouldn't": "should",
    "wouldn't": "would",
    "won't": "will",
}
ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.I)
HEADS = {"model", "network", "classifier", "predictor", "estimator"}
REFERENCE = re.compile(r"\b(?P<det>this|that|these|those)\s+(?P<head>[A-Za-z]+)\b", re.I)
BASE_SUBJECT = re.compile(
    r"^\s*((?:[\w-]+\s+){0,5}[\w-]+?)\s+(?:is|are|was|were|can|may|have|has)\b", re.I
)
ROLE_LABELS = {
    "USES": ("agent", "instrument"),
    "MEASURES": ("agent", "theme"),
    "PRODUCES": ("agent", "product"),
    "REQUIRES": ("theme", "prerequisite"),
    "DEPENDS_ON": ("dependent", "prerequisite"),
    "HAS_PART": ("whole", "part"),
    "LEADS_TO": ("cause", "effect"),
}


def _mentions(
    text: str, anchor: Span, sentence: tuple[int, int], match: re.Match, name: str
) -> TextSpan:
    start, end = match.span(name)
    if name != "predicate" and (
        article := ARTICLE.match(text[sentence[0] + start : sentence[0] + end])
    ):
        start += article.end()
    return anchor(sentence[0] + start, sentence[0] + end)


def _dependency_support(
    tokens: list[LinguisticToken], subject: TextSpan, predicate: TextSpan, obj: TextSpan
) -> bool:
    def inside(token: LinguisticToken, span: TextSpan) -> bool:
        return span.start <= token.span.start and token.span.end <= span.end

    predicates = {
        index
        for index, token in enumerate(tokens)
        if token.pos in {"VERB", "AUX"} and inside(token, predicate)
    }
    if not predicates:
        return False

    def linked(token: LinguisticToken) -> bool:
        head = token.head
        for _ in range(3):
            if head is None:
                return False
            if head in predicates:
                return True
            head = tokens[head].head
        return False

    return any(
        token.dependency in {"nsubj", "nsubjpass"} and inside(token, subject) and linked(token)
        for token in tokens
    ) and any(
        token.dependency in {"obj", "dobj", "pobj", "attr", "obl", "oprd"}
        and inside(token, obj)
        and linked(token)
        for token in tokens
    )


def find_relations(
    text: str, ranges: list[tuple[int, int]], anchor: Span, tokens: list[LinguisticToken]
) -> list[RelationCandidate]:
    candidates = []
    for start, end in ranges:
        piece = text[start:end]
        match = PATTERN.fullmatch(piece)
        if not match or piece.endswith("?") or UNSAFE_CLAUSE.search(piece):
            continue
        subject, predicate, obj = [
            _mentions(text, anchor, (start, end), match, key)
            for key in ("subject", "predicate", "object")
        ]
        if any(not 1 <= len(TOKEN.findall(span.text)) <= 12 for span in (subject, obj)):
            continue
        if subject.text.casefold() in {"it", "they", "he", "she", "this", "that", "we"}:
            continue
        kind = next(
            key
            for key, pattern in PREDICATES.items()
            if re.fullmatch(pattern, predicate.text, re.I)
        )
        negation = match["negation"]
        modality = match["modality"]
        if negation and modality is None:
            modality = MODAL_NEGATION.get(negation.casefold().replace("’", "'"))
        candidates.append(
            RelationCandidate(
                subject=subject,
                predicate=predicate,
                object=obj,
                evidence=anchor(start, end),
                type=kind,
                negated=bool(negation),
                modality=modality.casefold() if modality else None,
                method="dependency-pattern"
                if _dependency_support(tokens, subject, predicate, obj)
                else "lexical-pattern",
            )
        )
    return candidates


def frames(relations: list[RelationCandidate]) -> list[PredicateFrame]:
    return [
        PredicateFrame(
            predicate=relation.predicate,
            method=relation.method,
            negated=relation.negated,
            modality=relation.modality,
            arguments=[
                Role(label=labels[0], span=relation.subject),
                Role(label=labels[1], span=relation.object),
            ],
        )
        for relation in relations
        if (labels := ROLE_LABELS.get(relation.type))
    ]


def coreferences(
    text: str,
    ranges: list[tuple[int, int]],
    anchor: Span,
    phrases: list[NamedSpan],
) -> list[CoreferenceCandidate]:
    result = []
    for index, (start, end) in enumerate(ranges):
        if index:
            left, right = ranges[index - 1]
            first, last = anchor(left, right).start, anchor(left, right).end
            antecedents = [
                item.span for item in phrases if first <= item.span.start and item.span.end <= last
            ]
            if match := BASE_SUBJECT.match(text[left:right]):
                if not UNSAFE_CLAUSE.search(match[1]):
                    antecedents.append(anchor(left + match.start(1), left + match.end(1)))
        else:
            antecedents = []

        for reference in REFERENCE.finditer(text, start, end):
            noun = reference["head"].casefold()
            plural = reference["det"].casefold() in {"these", "those"}
            key = noun.removesuffix("s") if plural else noun
            matches = {}
            for span in antecedents:
                words = TOKEN.findall(span.text.casefold())
                if not words or (words[-1].endswith("s")) != plural:
                    continue
                head = words[-1].removesuffix("s") if plural else words[-1]
                if head == key or (key == "model" and head in HEADS):
                    matches[(span.start, span.end)] = span
            # Same mention with and without a determiner is one antecedent.
            alternatives = []
            for span in sorted(matches.values(), key=lambda item: (item.end, item.start)):
                if not alternatives or alternatives[-1].end != span.end:
                    alternatives.append(span)
            result.append(
                CoreferenceCandidate(
                    mention=anchor(*reference.span()),
                    alternatives=alternatives,
                    antecedent=alternatives[0] if len(alternatives) == 1 else None,
                    status="candidate"
                    if len(alternatives) == 1
                    else "ambiguous"
                    if alternatives
                    else "unresolved",
                )
            )
    return result
