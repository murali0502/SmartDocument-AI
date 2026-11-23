import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ingestion.extract import MAX_RESULT_BYTES
from smartdoc.persistence.ingestion_store import Claim, IngestionStore
from smartdoc.persistence.ncm_store import NcmStore
from smartdoc.persistence.nlp_store import NlpStore
from smartdoc.persistence.readiness import DatabaseReadiness
from smartdoc.persistence.structure_store import StructureStore

logger = logging.getLogger(__name__)


def process_environment() -> dict[str, str]:
    keep = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "TESSDATA_PREFIX",
        "SMARTDOC_TESSERACT",
    )
    return {
        **{key: os.environ[key] for key in keep if key in os.environ},
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_THREAD_LIMIT": "1",
    }


class IngestionWorker:
    def __init__(
        self,
        store: IngestionStore,
        readiness: DatabaseReadiness,
        timeout: int,
        *,
        structures: StructureStore | None = None,
        annotations: NlpStore | None = None,
        concepts: NcmStore | None = None,
    ) -> None:
        self.store = store
        self.readiness = readiness
        self.timeout = timeout
        self.structures = structures
        self.annotations = annotations
        self.concepts = concepts

    @cached_property
    def sandbox(self) -> str | None:
        executable = shutil.which("bwrap")
        if sys.platform != "linux" or not executable:
            return None
        try:
            with TemporaryDirectory() as source, TemporaryDirectory() as scratch:
                sample = Path(source) / "probe.txt"
                sample.write_bytes(b"SmartDoc parser readiness")
                output = Path(scratch) / "result.json"
                env = process_environment()
                command = self.command(
                    Claim("", "", sample, "txt"), output, env, sandbox=executable
                )
                probe = subprocess.run(
                    command,
                    env=env,
                    cwd=scratch,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if probe.returncode == 0:
                    payload = json.loads(output.read_bytes())
                    if payload["result"]["units"][0]["text"] == "SmartDoc parser readiness":
                        return executable
        except (OSError, ValueError, TypeError, KeyError, IndexError, subprocess.TimeoutExpired):
            pass
        logger.warning("ingestion_sandbox_unavailable")
        return None

    @staticmethod
    def command(
        claim: Claim, output: Path, env: dict[str, str], *, sandbox: str | None
    ) -> list[str]:
        args = [
            sys.executable,
            "-m",
            "smartdoc.ingestion.extract",
            str(claim.path),
            claim.format,
            str(output),
        ]
        if sandbox is None:
            return args
        command = [
            sandbox,
            "--unshare-all",
            "--die-with-parent",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        roots = {
            Path(path)
            for path in ("/usr", "/lib", "/lib64", "/bin", "/etc/fonts", "/etc/ld.so.cache")
        }
        roots.update(Path(path) for path in (sys.base_prefix, sys.prefix))
        roots.add(Path(__file__).resolve().parents[1])
        if executable := shutil.which(env.get("SMARTDOC_TESSERACT", "tesseract")):
            roots.add(Path(executable))
        if tessdata := env.get("TESSDATA_PREFIX"):
            roots.add(Path(tessdata).resolve())
        for root in sorted(roots):
            if root.exists():
                command.extend(("--ro-bind", str(root), str(root)))
        command.extend(
            (
                "--ro-bind",
                str(claim.path),
                str(claim.path),
                "--bind",
                str(output.parent),
                str(output.parent),
                "--chdir",
                str(output.parent),
                "--",
            )
        )
        return command + args

    def parse(self, claim: Claim) -> Extraction | ExtractionError:
        if not claim.path.is_file():
            return ExtractionError("original_missing", "The stored original could not be found.")
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            env = process_environment()
            try:
                with subprocess.Popen(
                    self.command(claim, output, env, sandbox=self.sandbox),
                    env=env,
                    cwd=directory,
                    start_new_session=os.name == "posix",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) as child:
                    try:
                        status = child.wait(timeout=self.timeout)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            try:
                                os.killpg(child.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        else:
                            child.kill()
                        child.wait()
                        return ExtractionError(
                            "processing_timeout", "The document exceeded the processing time limit."
                        )
                if status or not output.is_file() or output.stat().st_size > MAX_RESULT_BYTES:
                    return ExtractionError(
                        "parser_failed", "The parser exited before producing a result."
                    )
                payload = json.loads(output.read_bytes())
                if "result" not in payload:
                    return ExtractionError(payload["code"], payload["message"])
                result = Extraction.model_validate(payload["result"])
                result.metadata["isolation"] = "bubblewrap" if self.sandbox else "process"
                return result
            except (OSError, ValueError, KeyError, TypeError, ValidationError):
                return ExtractionError("parser_failed", "The extraction result could not be read.")

    def run_one(self) -> bool:
        claim = self.store.claim(self.timeout + 15)
        if claim is None:
            return False
        outcome = self.parse(claim)
        if self.store.finish(claim, outcome):
            logger.info(
                "ingestion_completed",
                extra={
                    "job_id": claim.job_id,
                    "error_type": outcome.code if isinstance(outcome, ExtractionError) else None,
                },
            )
        return True

    def run_until_stopped(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                if self.readiness.check() == "ready":
                    ingested = self.run_one()
                    structured = self.structures is not None and self.structures.build_next()
                    annotated = self.annotations is not None and self.annotations.build_next()
                    modeled = self.concepts is not None and self.concepts.build_next()
                    if ingested or structured or annotated or modeled:
                        continue
            except (OSError, SQLAlchemyError) as error:
                logger.warning("ingestion_worker_retry", extra={"error_type": type(error).__name__})
            stop.wait(0.6)
