import hashlib
import json
from collections.abc import Iterator
from functools import cached_property
from importlib.util import find_spec
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.nlp import lexical, relations
from smartdoc.nlp.assets import ENGLISH_VERSION
from smartdoc.nlp.contracts import Annotation, LinguisticToken, NamedSpan, TextSpan
from smartdoc.structure.contracts import Chunk

NLP_VERSION = "nlp-v1"
Profile = Literal["rules", "spacy"]


class LanguagePipeline:
    def __init__(self, profile: Profile, directory: Path, glossary: dict[str, list[str]]) -> None:
        self._load_lock = Lock()
        self.profile = profile
        self.directory = directory
        self.glossary = {
            label: sorted(set(terms), key=lambda term: (term.casefold(), term))
            for label, terms in sorted(glossary.items())
        }
        fingerprint = json.dumps([NLP_VERSION, self.method, self.glossary], ensure_ascii=False)
        self.key = hashlib.sha256(fingerprint.encode()).hexdigest()

    @property
    def method(self) -> str:
        return ENGLISH_VERSION if self.profile == "spacy" else "english-rules-v1"

    @cached_property
    def spacy(self) -> Any | None:
        path = self.directory / "english"
        if self.profile != "spacy" or find_spec("spacy") is None:
            return None
        if not (path / "installed.sha256").is_file():
            return None
        try:
            import spacy

            return spacy.load(path)
        except (OSError, ValueError, ImportError):
            return None

    @property
    def available(self) -> bool:
        if self.profile == "rules":
            return True
        with self._load_lock:
            return self.spacy is not None

    def annotate_batch(self, chunks: list[Chunk]) -> Iterator[Annotation]:
        if not self.available:
            raise ExtractionError(
                "model_unavailable", "The configured English spaCy model is unavailable."
            )
        if self.profile == "rules":
            for chunk in chunks:
                yield self._annotate(chunk, None)
            return

        selected = [chunk for chunk in chunks if lexical.is_english_script(chunk.text)]
        parsed = iter(self.spacy.pipe((chunk.text for chunk in selected), batch_size=8))
        selected_ids = {chunk.id for chunk in selected}
        for chunk in chunks:
            yield self._annotate(chunk, next(parsed) if chunk.id in selected_ids else None)

    def _annotate(self, chunk: Chunk, document: Any | None) -> Annotation:
        text = chunk.text

        def anchor(start: int, end: int) -> TextSpan:
            if not 0 <= start < end <= len(text):
                raise ValueError("Annotation spans must be inside the primary chunk.")
            offset = chunk.primary.start
            return TextSpan(start=offset + start, end=offset + end, text=text[start:end])

        dates = lexical.temporal(text, anchor)
        entities = lexical.entities(text, anchor, dates, self.glossary)
        warnings = []
        english = lexical.is_english_script(text)
        if not english:
            warnings.append("English linguistic interpretation is unavailable for this script.")

        phrases = []
        if document is None:
            token_rows = lexical.tokenize(text, anchor)
            sentence_ranges = lexical.sentences(text)
            if self.profile == "spacy":
                warnings.append("The English spaCy parser was skipped for this chunk.")
        else:
            visible = [token for token in document if not token.is_space]
            token_indices = {token.i: index for index, token in enumerate(visible)}
            token_rows = [
                LinguisticToken(
                    span=anchor(token.idx, token.idx + len(token.text)),
                    normalized=lexical.normalized(token.text),
                    lemma=token.lemma_ or None,
                    pos=token.pos_ or None,
                    dependency=token.dep_ or None,
                    head=token_indices.get(token.head.i) if token.head.i != token.i else None,
                )
                for token in visible
            ]
            sentence_ranges = [(span.start_char, span.end_char) for span in document.sents]
            entities.extend(
                NamedSpan(
                    span=anchor(span.start_char, span.end_char),
                    label=span.label_,
                    method=ENGLISH_VERSION,
                )
                for span in document.ents
            )
            phrases.extend(
                NamedSpan(
                    span=anchor(span.start_char, span.end_char),
                    label="noun_phrase",
                    method=ENGLISH_VERSION,
                )
                for span in document.noun_chunks
            )
        candidates = (
            relations.find_relations(text, sentence_ranges, anchor, token_rows) if english else []
        )
        for candidate in candidates:
            phrases.extend(
                NamedSpan(span=span, label="relation_argument", method=candidate.method)
                for span in (candidate.subject, candidate.object)
            )
        return Annotation(
            chunk_id=chunk.id,
            source=chunk.primary,
            language=lexical.language(text),
            method=self.method if document is not None else "english-rules-v1",
            warnings=warnings,
            sentences=[anchor(start, end) for start, end in sentence_ranges],
            tokens=token_rows,
            entities=self._unique(entities),
            phrases=self._unique(phrases),
            temporal=dates,
            relations=candidates,
            frames=relations.frames(candidates),
            coreferences=relations.coreferences(text, sentence_ranges, anchor, phrases)
            if english
            else [],
        )

    @staticmethod
    def _unique(items: list[NamedSpan]) -> list[NamedSpan]:
        unique = {}
        for item in items:
            unique.setdefault((item.span.start, item.span.end, item.label), item)
        return [unique[key] for key in sorted(unique)]
