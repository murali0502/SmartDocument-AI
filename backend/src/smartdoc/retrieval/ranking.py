import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from math import log
from unicodedata import normalize

TOKEN = re.compile(r"[^\W_]+")
STOP = frozenset(
    "a an and are as at be by for from how in is it of on or the to was what which who with".split()
)


def tokens(value: str) -> list[str]:
    return TOKEN.findall(normalize("NFKC", value).casefold())


def matches(query: set[str], label: str) -> bool:
    terms = set(tokens(label)) - STOP
    return bool(terms) and terms <= query


def bm25(texts: Iterable[list[str]], query: set[str]) -> dict[int, float]:
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    lengths = []
    for index, words in enumerate(texts):
        lengths.append(len(words))
        for word, count in Counter(words).items():
            if word in query:
                postings[word].append((index, count))
    average = sum(lengths) / max(len(lengths), 1) or 1
    scores: dict[int, float] = defaultdict(float)
    for word in sorted(postings):
        entries = postings[word]
        rarity = log(1 + (len(lengths) - len(entries) + 0.5) / (len(entries) + 0.5))
        for index, count in entries:
            norm = 1.2 * (0.25 + 0.75 * lengths[index] / average)
            scores[index] += rarity * count * 2.2 / (count + norm)
    return dict(scores)


def rank(
    words: list[list[str]],
    query: set[str],
    scores: dict[str, dict[int, float]],
    weights: dict[str, float],
    limit: int,
    rerank: bool,
    diversity: float,
) -> tuple[list[int], dict[int, float]]:
    fused: dict[int, float] = defaultdict(float)
    for method, values in scores.items():
        weight = weights.get(method, 1.0)
        if not weight:
            continue
        for position, index in enumerate(sorted(values, key=lambda i: (-values[i], i)), 1):
            fused[index] += weight / (60 + position)
    if rerank:
        for index in fused:
            coverage = len(set(words[index]) & query) / max(len(query), 1)
            fused[index] *= 1 + 0.15 * coverage
    ordered = sorted(fused, key=lambda i: (-fused[i], i))
    if not diversity or not ordered:
        return ordered, dict(fused)
    # Greedy MMR using token-set Jaccard similarity over a bounded shortlist.
    pool = ordered[: max(100, limit)]
    terms = {index: set(words[index]) for index in pool}
    redundancy = dict.fromkeys(pool, 0.0)
    peak = fused[ordered[0]]
    selected = []
    while pool and len(selected) < limit:
        best = max(
            pool, key=lambda i: (1 - diversity) * fused[i] / peak - diversity * redundancy[i]
        )
        selected.append(best)
        pool.remove(best)
        for index in pool:
            union = terms[index] | terms[best]
            similarity = len(terms[index] & terms[best]) / max(len(union), 1)
            redundancy[index] = max(redundancy[index], similarity)
    return selected + [index for index in ordered if index not in selected], dict(fused)
