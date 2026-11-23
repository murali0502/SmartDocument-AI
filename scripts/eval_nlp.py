"""Measure Phase 4 on the fixed, hand-labeled test set."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid5

from smartdoc.nlp.inference import LocalInference
from smartdoc.nlp.pipeline import LanguagePipeline
from smartdoc.structure.contracts import Chunk, SourceSpan

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evaluation" / "datasets" / "phase4-test.json"
NAMESPACE = UUID("7f7dcb71-4e2a-4927-84bb-f57b469dc987")


def sample(text: str, index: int) -> Chunk:
    return Chunk(
        id=uuid5(NAMESPACE, str(index)),
        document_id=NAMESPACE,
        parent_element_id=NAMESPACE,
        ordinal=index + 1,
        text=text,
        character_count=len(text),
        token_count=len(text.split()),
        locator={},
        section_path=[],
        element_type="paragraph",
        strategy="evaluation",
        primary=SourceSpan(unit=1, field=("text",), start=0, end=len(text)),
        overlap=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def metrics(gold: set, prediction: set) -> dict:
    matches = len(gold & prediction)
    precision = matches / len(prediction) if prediction else 0
    recall = matches / len(gold) if gold else 0
    return {
        "gold": len(gold),
        "predictions": len(prediction),
        "matches": matches,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if matches else 0,
    }


def linguistic(profile, path: Path, rows: list[dict]) -> dict:
    pipeline = LanguagePipeline(profile, path, {})
    start = perf_counter()
    results = list(
        pipeline.annotate_batch([sample(row["text"], i) for i, row in enumerate(rows)])
    )
    elapsed = perf_counter() - start
    output = {}
    for task in ("entities", "relations", "temporal", "coreference"):
        gold = {
            (i, *label) for i, row in enumerate(rows) for label in row.get(task, [])
        }
        predicted = set()
        for i, result in enumerate(results):
            values = {
                "entities": [(item.span.text, item.label) for item in result.entities],
                "relations": [
                    (item.subject.text, item.type, item.object.text, item.negated)
                    for item in result.relations
                ],
                "temporal": [
                    (item.span.text, item.normalized) for item in result.temporal
                ],
                "coreference": [
                    (item.mention.text, item.antecedent.text)
                    for item in result.coreferences
                    if item.antecedent is not None
                ],
            }
            predicted.update((i, *item) for item in values[task])
        output[task] = metrics(gold, predicted)
    output["duration_ms"] = round(elapsed * 1000, 1)
    return output


def dense(data: dict, models: LocalInference) -> dict:
    passages = data["passages"]
    examples = data["queries"]
    start = perf_counter()
    vectors, flags = models.embed([*passages, *(row[0] for row in examples)])
    total = perf_counter() - start
    assert not any(flags)
    ranks = []
    for row, (_, expected) in zip(vectors[len(passages) :], examples, strict=True):
        scores = [
            sum(a * b for a, b in zip(row, candidate, strict=True))
            for candidate in vectors[: len(passages)]
        ]
        ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
        ranks.append(ranked.index(expected) + 1)
    start = perf_counter()
    models.embed([examples[0][0]])
    return {
        "size": len(examples),
        "top_1": sum(rank == 1 for rank in ranks),
        "mrr": round(sum(1 / rank for rank in ranks) / len(ranks), 3),
        "ranks": ranks,
        "load_and_batch_ms": round(total * 1000, 1),
        "warm_query_ms": round((perf_counter() - start) * 1000, 1),
    }


def inference(data: dict, models: LocalInference) -> dict:
    examples = data["nli"]
    pairs = [(premise, hypothesis) for premise, hypothesis, _ in examples]
    start = perf_counter()
    scores, flags = models.infer(pairs)
    total = perf_counter() - start
    assert not any(flags)
    predictions = [max(row, key=row.__getitem__) for row in scores]
    start = perf_counter()
    models.infer(pairs[:1])
    return {
        "size": len(examples),
        "correct": sum(
            prediction == row[2]
            for prediction, row in zip(predictions, examples, strict=True)
        ),
        "predictions": predictions,
        "load_and_batch_ms": round(total * 1000, 1),
        "warm_pair_ms": round((perf_counter() - start) * 1000, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        type=Path,
        help="Run optional spaCy, embedding and NLI tests from this directory.",
    )
    args = parser.parse_args()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = {"rules": linguistic("rules", Path("."), data["linguistic"])}
    if args.models:
        report["spacy"] = linguistic("spacy", args.models, data["linguistic"])
        runtime = LocalInference(args.models)
        report["embedding"] = dense(data, runtime)
        report["nli"] = inference(data, runtime)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
