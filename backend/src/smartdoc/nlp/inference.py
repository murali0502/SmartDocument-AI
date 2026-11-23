from hashlib import file_digest
from pathlib import Path
from threading import Lock
from typing import Any

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.nlp.assets import ASSETS

MAX_MODEL_TOKENS = 256
NLI_LABELS = ("contradiction", "entailment", "neutral")


class LocalInference:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._models: dict[str, tuple[Any, Any]] = {}
        self._lock = Lock()

    def _load(self, name: str) -> tuple[Any, Any]:
        if name in self._models:
            return self._models[name]
        path = self.root / name
        if not (path / "installed.sha256").is_file():
            raise ExtractionError("model_unavailable", f"The local {name} model is not installed.")
        try:
            for asset in ASSETS[name]:
                with (path / asset.name).open("rb") as file:
                    if file_digest(file, "sha256").hexdigest() != asset.sha256:
                        raise ValueError("Model asset checksum mismatch.")
            import onnxruntime
            from tokenizers import Tokenizer

            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            model = onnxruntime.InferenceSession(
                str(path / "model.onnx"), options, providers=["CPUExecutionProvider"]
            )
            tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
            tokenizer.enable_truncation(max_length=MAX_MODEL_TOKENS)
            tokenizer.enable_padding()
        except Exception as error:
            raise ExtractionError(
                "model_unavailable", f"The local {name} model could not start."
            ) from error
        self._models[name] = (model, tokenizer)
        return model, tokenizer

    def _inputs(self, name: str, texts: list, np: Any) -> tuple[Any, dict, list[bool]]:
        model, tokenizer = self._load(name)
        encoded = tokenizer.encode_batch(texts)
        columns = {
            "input_ids": "ids",
            "attention_mask": "attention_mask",
            "token_type_ids": "type_ids",
        }
        inputs = {
            key.name: np.asarray(
                [getattr(row, columns[key.name]) for row in encoded], dtype=np.int64
            )
            for key in model.get_inputs()
        }
        return model, inputs, [bool(row.overflowing) for row in encoded]

    def embed(self, texts: list[str]) -> tuple[list[list[float]], list[bool]]:
        with self._lock:
            self._load("embedding")
            import numpy as np

            model, inputs, truncated = self._inputs("embedding", texts, np)
            hidden, *_ = model.run(None, inputs)
            mask = inputs["attention_mask"][..., None]
            means = (hidden * mask).sum(axis=1) / mask.sum(axis=1)
            lengths = np.linalg.norm(means, axis=1, keepdims=True)
            return (means / np.maximum(lengths, 1e-12)).tolist(), truncated

    def infer(self, pairs: list[tuple[str, str]]) -> tuple[list[dict[str, float]], list[bool]]:
        with self._lock:
            self._load("nli")
            import numpy as np

            model, inputs, truncated = self._inputs("nli", pairs, np)
            logits, *_ = model.run(None, inputs)
            exp = np.exp(logits - logits.max(axis=1, keepdims=True))
            values = exp / exp.sum(axis=1, keepdims=True)
            return [dict(zip(NLI_LABELS, row, strict=True)) for row in values.tolist()], truncated
