"""Explicit installer for pinned, local NLP data. The API never downloads models."""

import argparse
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

ENGLISH_VERSION = "en_core_web_sm-3.8.0"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
NLI_REVISION = "b95119ce93d3e065de6214e38cd4a97b0f2f2c6d"
DEFAULT_MODELS = Path(".local") / "nlp-models"
MAX_ASSET_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str


def hub(repo: str, revision: str, path: str, digest: str) -> Asset:
    return Asset(
        PurePosixPath(path).name, f"https://huggingface.co/{repo}/resolve/{revision}/{path}", digest
    )


def graph(repo: str, revision: str, digest: str) -> Asset:
    asset = hub(repo, revision, "onnx/model_quint8_avx2.onnx", digest)
    return Asset("model.onnx", asset.url, asset.sha256)


ENGLISH_WHEEL = f"{ENGLISH_VERSION}-py3-none-any.whl"
EMBEDDING_REPO = "sentence-transformers/all-MiniLM-L6-v2"
NLI_REPO = "cross-encoder/nli-MiniLM2-L6-H768"
ASSETS = {
    "english": (
        Asset(
            ENGLISH_WHEEL,
            f"https://github.com/explosion/spacy-models/releases/download/{ENGLISH_VERSION}/{ENGLISH_WHEEL}",
            "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85",
        ),
    ),
    "embedding": (
        graph(
            EMBEDDING_REPO,
            EMBEDDING_REVISION,
            "b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21",
        ),
        hub(
            EMBEDDING_REPO,
            EMBEDDING_REVISION,
            "tokenizer.json",
            "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
        ),
    ),
    "nli": (
        graph(
            NLI_REPO,
            NLI_REVISION,
            "44391a5241a62e0083c1a8899a71e69a092b95aea5ba89e14062925468eceac7",
        ),
        hub(
            NLI_REPO,
            NLI_REVISION,
            "tokenizer.json",
            "82139106e603ee4e1d5bc99d056ccbed5a92bc24848b1b5a7137c26e00d0dbf6",
        ),
    ),
}


def download(asset: Asset, destination: Path) -> None:
    digest = hashlib.sha256()
    size = 0
    with urlopen(asset.url, timeout=30) as source, destination.open("wb") as output:
        while block := source.read(1024 * 1024):
            size += len(block)
            if size > MAX_ASSET_BYTES:
                raise ValueError(f"Model download exceeds the size limit: {asset.name}")
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != asset.sha256:
        raise ValueError(f"Model checksum does not match: {asset.name}")


def extract_english(wheel: Path, output: Path) -> None:
    prefix = PurePosixPath("en_core_web_sm") / ENGLISH_VERSION
    with ZipFile(wheel) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if member.is_dir() or not path.is_relative_to(prefix):
                continue
            relative = path.relative_to(prefix)
            if ".." in relative.parts or any("\\" in part for part in relative.parts):
                raise ValueError("Invalid model archive path.")
            destination = output.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    if not (output / "config.cfg").is_file():
        raise ValueError("Missing spaCy configuration in the model archive.")


def install(root: Path, model: str) -> None:
    destination = root / model
    if (destination / "installed.sha256").is_file():
        print(f"{model} is already installed at {destination}")
        return
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        staged = Path(directory) / "files"
        staged.mkdir()
        for asset in ASSETS[model]:
            download(asset, staged / asset.name)
        if model == "english":
            extract_english(staged / ENGLISH_WHEEL, staged)
            (staged / ENGLISH_WHEEL).unlink()
        (staged / "installed.sha256").write_text(
            "\n".join(asset.sha256 for asset in ASSETS[model]), encoding="ascii"
        )
        staged.rename(destination)
    print(f"Installed {model} at {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", choices=tuple(ASSETS))
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(os.getenv("SMARTDOC_NLP_MODEL_DIR", str(DEFAULT_MODELS))),
    )
    args = parser.parse_args()
    for model in dict.fromkeys(args.models):
        install(args.directory.resolve(), model)


if __name__ == "__main__":
    main()
