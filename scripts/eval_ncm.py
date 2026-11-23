"""Evaluate deterministic Phase 5 outputs against labeled document fixtures."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid5

from eval_nlp import metrics
from smartdoc.ingestion.contracts import Extraction, SourceUnit
from smartdoc.ncm.candidates import Inputs, normalized
from smartdoc.ncm.contracts import Weights
from smartdoc.ncm.model import build_snapshot
from smartdoc.nlp.pipeline import LanguagePipeline
from smartdoc.structure.builder import build_structure
from smartdoc.structure.contracts import resolve_span

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evaluation" / "datasets" / "phase5-test.json"
NAMESPACE = UUID("23258993-9d2d-4d29-85c5-10364751dcda")


def run(path: Path | None, weights: Weights) -> dict:
    profile = LanguagePipeline("spacy" if path else "rules", path or Path("."), {})
    examples = json.loads(FIXTURE.read_text(encoding="utf-8"))["examples"]
    tasks = ("concepts", "relations", "aliases", "ambiguous")
    gold = {task: set() for task in tasks}
    predictions = {task: set() for task in tasks}
    verified = 0
    started = perf_counter()
    for index, row in enumerate(examples):
        doc = uuid5(NAMESPACE, f"document:{index}")
        job = uuid5(NAMESPACE, f"job:{index}")
        extraction = Extraction(
            format="md",
            parser="evaluation",
            parser_version="1",
            units=[SourceUnit(kind="document", text=row["text"])],
        )
        at = datetime(2026, 1, 1, tzinfo=UTC)
        chunks = build_structure(doc, job, extraction, at).chunks
        result = build_snapshot(
            doc,
            job,
            extraction,
            (
                Inputs(chunk, annotation)
                for chunk, annotation in zip(
                    chunks, profile.annotate_batch(chunks), strict=True
                )
            ),
            at,
            weights,
        )
        concepts = {item.id: item.normalized for item in result.concepts}
        outputs = {
            "concepts": [(value,) for value in concepts.values()],
            "relations": [
                (
                    concepts[item.subject_id],
                    item.type,
                    concepts[item.object_id],
                    item.negated,
                )
                for item in result.assertions
                if item.validation == "source_validated"
            ],
            "aliases": [
                (normalized(alias.surface), item.normalized)
                for item in result.concepts
                for alias in item.aliases
            ],
            "ambiguous": [
                (normalized(item.surface),) for item in result.ambiguous_aliases
            ],
        }
        for task in tasks:
            gold[task].update(
                (index, *(entry if isinstance(entry, list) else [entry]))
                for entry in row[task]
            )
            predictions[task].update((index, *item) for item in outputs[task])
        anchors = [
            mention.evidence for item in result.concepts for mention in item.mentions
        ]
        anchors.extend(
            anchor
            for item in result.assertions
            for anchor in (item.subject, item.object, item.predicate, item.evidence)
        )
        anchors.extend(anchor for item in result.hierarchy for anchor in item.evidence)
        for anchor in anchors:
            assert resolve_span(extraction, anchor.source) == anchor.text
            verified += 1
    return {
        "profile": profile.method,
        "documents": len(examples),
        "verified_anchors": verified,
        "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        **{task: metrics(gold[task], predictions[task]) for task in tasks},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        type=Path,
        help="Use the optional spaCy profile with this model cache.",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.models, Weights()), indent=2))


if __name__ == "__main__":
    main()
