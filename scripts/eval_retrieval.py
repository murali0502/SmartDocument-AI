"""Evaluate retrieval and source round trips against frozen technical passages."""

import argparse
import json
import os
import resource
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Any
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from smartdoc.app import create_app
from smartdoc.config import MIGRATIONS_DIR, Settings

BASE = "/api/v1/workspaces/local"
DATASET = Path(__file__).resolve().parents[1] / "evaluation/datasets/phase7-test.json"
VARIANTS = {
    "bm25": {"methods": ["bm25"], "rerank": False},
    "structure": {"methods": ["structure"], "rerank": False},
    "concept": {"methods": ["concept"], "rerank": False},
    "graph": {"methods": ["graph"], "rerank": False},
    "dense": {"methods": ["dense"], "rerank": False},
    "bm25_structure": {"methods": ["bm25", "structure"], "rerank": False},
    "bm25_structure_concept": {
        "methods": ["bm25", "structure", "concept"],
        "rerank": False,
    },
    "fusion": {"methods": ["bm25", "structure", "concept", "graph"], "rerank": False},
    "reranked": {"methods": ["bm25", "structure", "concept", "graph"]},
    "diverse": {"methods": ["bm25", "structure", "concept", "graph"], "diversity": 0.2},
    "all": {
        "methods": ["bm25", "structure", "concept", "graph", "dense"],
        "diversity": 0.2,
    },
}


def evaluate(client: TestClient, queries: list[dict], options: dict) -> dict[str, Any]:
    durations = []
    reciprocal = []
    recalls = []
    corpus_size = 0
    for case in queries:
        response = client.post(
            f"{BASE}/search", json={**options, "query": case["query"], "limit": 5}
        )
        response.raise_for_status()
        data = response.json()
        diagnostics = data["diagnostics"]
        corpus_size = diagnostics["corpus_chunks"]
        durations.append(diagnostics["duration_ms"])
        matched = set()
        first = 0.0
        for rank, hit in enumerate(data["items"], 1):
            source = client.get(hit["source_url"])
            source.raise_for_status()
            if hit["evidence"] != source.json()["primary"]:
                raise ValueError("Search excerpt differs from the source endpoint.")
            for passage in case["passages"]:
                if passage in hit["evidence"]["text"]:
                    first = first or 1 / rank
                    matched.add(passage)
        reciprocal.append(first)
        recalls.append(len(matched) / len(case["passages"]))
    return {
        "chunks": corpus_size,
        "mrr_at_5": round(sum(reciprocal) / len(queries), 3),
        "recall_at_5": round(sum(recalls) / len(queries), 3),
        "p50_ms": round(median(durations), 2),
        "p95_ms": round(quantiles(durations, n=20, method="inclusive")[-1], 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", type=Path, help="Directory containing installed embedding assets"
    )
    parser.add_argument("--distractors", type=int, default=0)
    args = parser.parse_args()
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    documents = dataset["documents"]
    for index in range(args.distractors):
        documents[f"noise-{index}.md"] = (
            f"# Maintenance log {index}\n\nThe motor and pump were inspected. "
            "Battery, housing and valve conditions were recorded."
        )

    with TemporaryDirectory() as directory:
        database = Path(directory) / "benchmark.sqlite3"
        settings = Settings(database_path=database)
        if args.models:
            settings.nlp_model_dir = args.models.resolve()
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with patch.dict(os.environ, SMARTDOC_DATABASE_PATH=str(database)):
            command.upgrade(config, "head")
        app = create_app(settings)
        with TestClient(
            app, base_url="http://localhost", client=("127.0.0.1", 50000)
        ) as client:
            for filename, content in documents.items():
                upload = client.post(
                    f"{BASE}/uploads",
                    params={"filename": filename},
                    content=content.encode(),
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-SmartDoc-Upload": "1",
                    },
                )
                upload.raise_for_status()

            deadline = monotonic() + 120
            while monotonic() < deadline:
                latest = client.get(f"{BASE}/graph").json()["latest"]
                if (
                    latest
                    and latest["status"] == "ready"
                    and latest["document_count"] == len(documents)
                ):
                    break
                sleep(0.2)
            else:
                raise RuntimeError(
                    "Collection graph did not publish all benchmark documents."
                )

            if args.models:
                app.state.local_inference.embed(["Warm embedding session."])
            results = {
                name: evaluate(client, dataset["queries"], options)
                for name, options in VARIANTS.items()
                if args.models or "dense" not in options["methods"]
            }
    print(
        json.dumps(
            {
                "documents": len(documents),
                "queries": len(dataset["queries"]),
                "peak_rss_mib_linux": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
                ),
                "variants": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
