from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class TextEncoder(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def resolved_revision(self) -> str: ...

    def encode_queries(self, texts: Sequence[str]) -> object: ...

    def encode_documents(self, texts: Sequence[str]) -> object: ...


@dataclass(frozen=True, slots=True)
class EncoderConfiguration:
    name: str
    model_id: str
    revision: str = "main"
    query_prompt: str | None = None
    query_prompt_name: str | None = None


ENCODER_CONFIGURATIONS = {
    "arctic-s": EncoderConfiguration(
        name="arctic-s",
        model_id="Snowflake/snowflake-arctic-embed-s",
        query_prompt_name="query",
    ),
    "bge-small": EncoderConfiguration(
        name="bge-small",
        model_id="BAAI/bge-small-en-v1.5",
    ),
    "arctic-xs": EncoderConfiguration(
        name="arctic-xs",
        model_id="Snowflake/snowflake-arctic-embed-xs",
        query_prompt_name="query",
    ),
    "minilm-l6": EncoderConfiguration(
        name="minilm-l6",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
    ),
}


class SentenceTransformerEncoder:
    """Lazy experiment adapter; importing this module has no ML dependency."""

    def __init__(
        self,
        configuration: EncoderConfiguration,
        *,
        batch_size: int = 64,
        device: str = "cpu",
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "install the semantic-experiment optional dependencies"
            ) from error
        self.configuration = configuration
        self._batch_size = batch_size
        self._model = SentenceTransformer(
            configuration.model_id,
            revision=configuration.revision,
            device=device,
        )
        dimension_getter = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        self._dimension = int(dimension_getter())
        first_module = self._model[0]
        auto_model = getattr(first_module, "auto_model", None)
        config = getattr(auto_model, "config", None)
        self._resolved_revision = str(
            getattr(config, "_commit_hash", None) or configuration.revision
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def resolved_revision(self) -> str:
        return self._resolved_revision

    def encode_queries(self, texts: Sequence[str]) -> object:
        arguments: dict[str, object] = {}
        if self.configuration.query_prompt_name:
            arguments["prompt_name"] = self.configuration.query_prompt_name
        elif self.configuration.query_prompt:
            arguments["prompt"] = self.configuration.query_prompt
        return self._encode(texts, **arguments)

    def encode_documents(self, texts: Sequence[str]) -> object:
        return self._encode(texts)

    def _encode(self, texts: Sequence[str], **arguments: object) -> object:
        return self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            **arguments,
        )
