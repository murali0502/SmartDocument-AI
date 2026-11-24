"""Copy a consistent SmartDoc SQLite database and verify its referenced originals."""

import argparse
import json
import re
import shutil
import sqlite3
from contextlib import closing
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory


def snapshot(database: Path, storage: Path, destination: Path) -> int:
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary) / "workspace"
        staging.mkdir(mode=0o700)
        with (
            closing(
                sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
            ) as source,
            closing(sqlite3.connect(staging / "smartdoc.sqlite3")) as copied,
        ):
            source.backup(copied)
            if copied.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Snapshot database failed its integrity check.")
            originals = copied.execute(
                "SELECT workspace_id, sha256 FROM documents ORDER BY workspace_id, sha256"
            ).fetchall()
        uploads = staging / "uploads"
        uploads.mkdir()
        for workspace, digest in originals:
            if not re.fullmatch(r"[0-9a-f-]{36}", workspace) or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                raise ValueError("An original record contains an invalid storage key.")
            relative = Path("originals", workspace, digest[:2], digest)
            backup = uploads / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(storage / relative, backup)
            with backup.open("rb") as file:
                if file_digest(file, "sha256").hexdigest() != digest:
                    raise ValueError(
                        "An original file does not match its stored digest."
                    )
        (staging / "snapshot.json").write_text(
            json.dumps({"format": 1, "verified_originals": len(originals)}) + "\n",
            encoding="utf-8",
        )
        staging.rename(destination)
    return len(originals)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    count = snapshot(args.database, args.storage, args.destination)
    print(f"Snapshot created with {count} verified original files.")


if __name__ == "__main__":
    main()
