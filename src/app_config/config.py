from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULT_REMOTE_FETCH_USER_AGENT = "Paper Notes/0.1 (+https://localhost)"
DEFAULT_REMOTE_FETCH_ACCEPT = "application/pdf,text/html;q=0.8,*/*;q=0.5"

DEFAULT_RAG_ROOT = PROJECT_ROOT / ".paper-notes" / "rag"
DEFAULT_RAG_INDEX_ROOT = DEFAULT_RAG_ROOT / "indexes"
DEFAULT_RAG_IMAGE_ROOT = DEFAULT_RAG_ROOT / "images"
DEFAULT_TEXT_COLLECTION = "paper_notes"
DEFAULT_IMAGE_COLLECTION = "paper_notes_images"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_OPENAI_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_EMBEDDING_PROVIDER = "ollama"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "qwen3-embedding:8b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_EMBED_BATCH_SIZE = 100
DEFAULT_IMAGE_EMBEDDING_MODEL = "ViT-B/32"
DEFAULT_LOADER = "pymupdf"
DEFAULT_LLAMAPARSE_TIER = "agentic"
DEFAULT_LLAMAPARSE_VERSION = "latest"
DEFAULT_LLAMAPARSE_TIMEOUT = 7200.0
DEFAULT_LLAMAPARSE_POLLING_INTERVAL = 2.0
DEFAULT_LLAMAPARSE_MAX_INTERVAL = 20.0
DEFAULT_LLAMAPARSE_IMAGE_DOWNLOAD_TIMEOUT = 60.0
DEFAULT_LLAMAPARSE_CUSTOM_PROMPT = (
    "Parse this academic paper into clean Markdown. Preserve section headings, "
    "equations, citations, figure captions, table captions, tables, and references. "
    "Keep the reading order correct for multi-column paper layouts."
)
DEFAULT_LLAMAPARSE_IMAGE_CATEGORIES = ("embedded", "layout")
DEFAULT_SIMILARITY_TOP_K = 5
DEFAULT_IMAGE_SIMILARITY_TOP_K = 3
DEFAULT_BM25_SIMILARITY_TOP_K = 5
DEFAULT_HYBRID_WEIGHTS = (0.7, 0.3)
DEFAULT_INDEX_KEY = "default"
DEFAULT_TOOL_OUTPUT_ROOT = PROJECT_ROOT / ".paper-notes" / "tool-outputs"


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    title: str = "Paper Notes"
    docs_url: str = "/docs"

    @classmethod
    def from_mapping(cls, value: object) -> ServerConfig:
        data = _mapping(value)
        return cls(
            host=_text(data, "host", default="127.0.0.1"),
            port=_int(data, "port", default=8765, minimum=1),
            title=_text(data, "title", default="Paper Notes"),
            docs_url=_text(data, "docs_url", "docsUrl", default="/docs"),
        )


@dataclass(frozen=True, slots=True)
class ContextManagementConfig:
    enabled: bool = True

    @classmethod
    def from_mapping(cls, value: object) -> ContextManagementConfig:
        data = _mapping(value)
        return cls(enabled=_bool(data, "enabled", default=True))


@dataclass(frozen=True, slots=True)
class ContextCollapseConfig:
    trigger_messages: int = 40
    trigger_tokens: int = 40_000

    @classmethod
    def from_mapping(cls, value: object) -> ContextCollapseConfig:
        data = _mapping(value)
        return cls(
            trigger_messages=_int(
                data,
                "trigger_messages",
                "triggerMessages",
                default=40,
                minimum=1,
            ),
            trigger_tokens=_int(
                data,
                "trigger_tokens",
                "triggerTokens",
                default=40_000,
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class ContextCompactionConfig:
    reserve_tokens: int = 20_000

    @classmethod
    def from_mapping(cls, value: object) -> ContextCompactionConfig:
        data = _mapping(value)
        return cls(
            reserve_tokens=_int(
                data,
                "reserve_tokens",
                "reserveTokens",
                default=20_000,
                minimum=0,
            )
        )


@dataclass(frozen=True, slots=True)
class ToolOutputConfig:
    enabled: bool = True
    root_dir: Path = DEFAULT_TOOL_OUTPUT_ROOT
    default_max_tokens: int = 8_000
    placeholder_keep_recent: int = 8
    tool_limits: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: object) -> ToolOutputConfig:
        data = _mapping(value)
        default_max_tokens = _int(
            data,
            "default_max_tokens",
            "defaultMaxTokens",
            default=8_000,
            minimum=1,
        )
        return cls(
            enabled=_bool(data, "enabled", default=True),
            root_dir=_path(data, "root_dir", "rootDir", "output_dir", "outputDir", default=DEFAULT_TOOL_OUTPUT_ROOT),
            default_max_tokens=default_max_tokens,
            placeholder_keep_recent=_int(
                data,
                "placeholder_keep_recent",
                "placeholderKeepRecent",
                default=8,
                minimum=1,
            ),
            tool_limits=_tool_limits(data.get("tool_limits", data.get("toolLimits"))),
        )

    def limit_for(self, tool_name: str) -> int:
        return self.tool_limits.get(str(tool_name or ""), self.default_max_tokens)


@dataclass(frozen=True, slots=True)
class LibraryImportConfig:
    max_pdf_bytes: int = 120 * 1024 * 1024
    max_html_bytes: int = 2 * 1024 * 1024
    timeout_seconds: float = 45.0
    arxiv_timeout_seconds: float = 12.0
    chunk_size: int = 64 * 1024
    user_agent: str = DEFAULT_REMOTE_FETCH_USER_AGENT
    accept: str = DEFAULT_REMOTE_FETCH_ACCEPT

    @classmethod
    def from_mapping(cls, value: object) -> LibraryImportConfig:
        data = _mapping(value)
        return cls(
            max_pdf_bytes=_int(data, "max_pdf_bytes", "maxPdfBytes", default=120 * 1024 * 1024, minimum=1),
            max_html_bytes=_int(data, "max_html_bytes", "maxHtmlBytes", default=2 * 1024 * 1024, minimum=1),
            timeout_seconds=_float(data, "timeout_seconds", "timeoutSeconds", default=45.0, minimum=0.1),
            arxiv_timeout_seconds=_float(
                data,
                "arxiv_timeout_seconds",
                "arxivTimeoutSeconds",
                default=12.0,
                minimum=0.1,
            ),
            chunk_size=_int(data, "chunk_size", "chunkSize", default=64 * 1024, minimum=1),
            user_agent=_text(data, "user_agent", "userAgent", default=DEFAULT_REMOTE_FETCH_USER_AGENT),
            accept=_text(data, "accept", default=DEFAULT_REMOTE_FETCH_ACCEPT),
        )

    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
        }


@dataclass(frozen=True, slots=True)
class LibraryConfig:
    import_settings: LibraryImportConfig = field(default_factory=LibraryImportConfig)

    @classmethod
    def from_mapping(cls, value: object) -> LibraryConfig:
        data = _mapping(value)
        return cls(import_settings=LibraryImportConfig.from_mapping(data.get("import")))


@dataclass(frozen=True, slots=True)
class RagCollectionsConfig:
    text: str = DEFAULT_TEXT_COLLECTION
    image: str = DEFAULT_IMAGE_COLLECTION

    @classmethod
    def from_mapping(cls, value: object) -> RagCollectionsConfig:
        data = _mapping(value)
        return cls(
            text=_text(data, "text", "textCollection", default=DEFAULT_TEXT_COLLECTION),
            image=_text(data, "image", "imageCollection", default=DEFAULT_IMAGE_COLLECTION),
        )


@dataclass(frozen=True, slots=True)
class RagBuildConfig:
    loader: str = DEFAULT_LOADER
    include_images: bool = False
    qdrant: bool = True
    bm25: bool = True

    @classmethod
    def from_mapping(cls, value: object) -> RagBuildConfig:
        data = _mapping(value)
        loader = _text(data, "loader", default=DEFAULT_LOADER).lower()
        return cls(
            loader=loader if loader in {"pymupdf", "llamaparse"} else DEFAULT_LOADER,
            include_images=_bool(data, "include_images", "includeImages", default=False),
            qdrant=_bool(data, "qdrant", "buildQdrant", default=True),
            bm25=_bool(data, "bm25", "buildBm25", default=True),
        )


@dataclass(frozen=True, slots=True)
class RagChunkingConfig:
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP

    @classmethod
    def from_mapping(cls, value: object) -> RagChunkingConfig:
        data = _mapping(value)
        size = _int(data, "chunk_size", "chunkSize", default=DEFAULT_CHUNK_SIZE, minimum=1)
        overlap = _int(data, "chunk_overlap", "chunkOverlap", default=DEFAULT_CHUNK_OVERLAP, minimum=0)
        return cls(chunk_size=size, chunk_overlap=min(overlap, max(0, size - 1)))


@dataclass(frozen=True, slots=True)
class RagOllamaEmbeddingConfig:
    model: str = ""
    base_url: str = DEFAULT_OLLAMA_BASE_URL

    @classmethod
    def from_mapping(cls, value: object) -> RagOllamaEmbeddingConfig:
        data = _mapping(value)
        return cls(
            model=_text(data, "model", default=""),
            base_url=_text(data, "base_url", "baseUrl", default=DEFAULT_OLLAMA_BASE_URL),
        )


@dataclass(frozen=True, slots=True)
class RagOpenAIEmbeddingConfig:
    model: str = ""
    api_base: str = ""
    api_base_env: str = "MODELSCOPE_BASEURL"
    api_key_env: str = "MODELSCOPE_TOKEN"

    @classmethod
    def from_mapping(cls, value: object) -> RagOpenAIEmbeddingConfig:
        data = _mapping(value)
        return cls(
            model=_text(data, "model", default=""),
            api_base=_text(data, "api_base", "apiBase", default=""),
            api_base_env=_text(data, "api_base_env", "apiBaseEnv", default="MODELSCOPE_BASEURL"),
            api_key_env=_text(data, "api_key_env", "apiKeyEnv", default="MODELSCOPE_TOKEN"),
        )


@dataclass(frozen=True, slots=True)
class RagEmbeddingConfig:
    provider: str = DEFAULT_EMBEDDING_PROVIDER
    model: str = ""
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE
    ollama: RagOllamaEmbeddingConfig = field(default_factory=RagOllamaEmbeddingConfig)
    openai: RagOpenAIEmbeddingConfig = field(default_factory=RagOpenAIEmbeddingConfig)

    @classmethod
    def from_mapping(cls, value: object) -> RagEmbeddingConfig:
        data = _mapping(value)
        return cls(
            provider=_text(data, "provider", default=DEFAULT_EMBEDDING_PROVIDER).lower(),
            model=_text(data, "model", default=""),
            batch_size=_int(data, "batch_size", "batchSize", default=DEFAULT_EMBED_BATCH_SIZE, minimum=1),
            ollama=RagOllamaEmbeddingConfig.from_mapping(data.get("ollama")),
            openai=RagOpenAIEmbeddingConfig.from_mapping(data.get("openai")),
        )

    def provider_name(self, value: str | None = None) -> str:
        return str(value or self.provider).strip().lower() or DEFAULT_EMBEDDING_PROVIDER

    def model_for(self, provider: str | None = None, override: str | None = None) -> str | None:
        if override:
            return str(override).strip()
        provider_name = self.provider_name(provider)
        if provider_name == "openai":
            return self.openai.model or self.model or DEFAULT_OPENAI_EMBEDDING_MODEL
        if provider_name == "ollama":
            return self.ollama.model or self.model or DEFAULT_OLLAMA_EMBEDDING_MODEL
        return self.model or None


@dataclass(frozen=True, slots=True)
class RagImageEmbeddingConfig:
    model: str = DEFAULT_IMAGE_EMBEDDING_MODEL

    @classmethod
    def from_mapping(cls, value: object) -> RagImageEmbeddingConfig:
        data = _mapping(value)
        return cls(model=_text(data, "model", default=DEFAULT_IMAGE_EMBEDDING_MODEL))


@dataclass(frozen=True, slots=True)
class RagRetrievalConfig:
    similarity_top_k: int = DEFAULT_SIMILARITY_TOP_K
    image_similarity_top_k: int = DEFAULT_IMAGE_SIMILARITY_TOP_K
    bm25_similarity_top_k: int = DEFAULT_BM25_SIMILARITY_TOP_K
    hybrid_weights: tuple[float, float] = DEFAULT_HYBRID_WEIGHTS

    @classmethod
    def from_mapping(cls, value: object) -> RagRetrievalConfig:
        data = _mapping(value)
        return cls(
            similarity_top_k=_int(
                data,
                "similarity_top_k",
                "similarityTopK",
                default=DEFAULT_SIMILARITY_TOP_K,
                minimum=1,
                maximum=20,
            ),
            image_similarity_top_k=_int(
                data,
                "image_similarity_top_k",
                "imageSimilarityTopK",
                default=DEFAULT_IMAGE_SIMILARITY_TOP_K,
                minimum=1,
                maximum=20,
            ),
            bm25_similarity_top_k=_int(
                data,
                "bm25_similarity_top_k",
                "bm25SimilarityTopK",
                default=DEFAULT_BM25_SIMILARITY_TOP_K,
                minimum=1,
                maximum=20,
            ),
            hybrid_weights=_float_pair(data, "hybrid_weights", "hybridWeights", default=DEFAULT_HYBRID_WEIGHTS),
        )

    def similarity_top_k_for(self, value: int | None = None) -> int:
        return _bounded_int(value, default=self.similarity_top_k, minimum=1, maximum=20)

    def image_similarity_top_k_for(self, value: int | None = None) -> int:
        return _bounded_int(value, default=self.image_similarity_top_k, minimum=1, maximum=20)

    def bm25_similarity_top_k_for(self, value: int | None = None) -> int:
        return _bounded_int(value, default=self.bm25_similarity_top_k, minimum=1, maximum=20)


@dataclass(frozen=True, slots=True)
class RagLlamaParseConfig:
    tier: str = DEFAULT_LLAMAPARSE_TIER
    version: str = DEFAULT_LLAMAPARSE_VERSION
    timeout: float = DEFAULT_LLAMAPARSE_TIMEOUT
    polling_interval: float = DEFAULT_LLAMAPARSE_POLLING_INTERVAL
    max_interval: float = DEFAULT_LLAMAPARSE_MAX_INTERVAL
    image_download_timeout: float = DEFAULT_LLAMAPARSE_IMAGE_DOWNLOAD_TIMEOUT
    image_categories: tuple[str, ...] = DEFAULT_LLAMAPARSE_IMAGE_CATEGORIES
    ocr_languages: tuple[str, ...] = ()
    custom_prompt: str = DEFAULT_LLAMAPARSE_CUSTOM_PROMPT

    @classmethod
    def from_mapping(cls, value: object) -> RagLlamaParseConfig:
        data = _mapping(value)
        return cls(
            tier=_text(data, "tier", default=DEFAULT_LLAMAPARSE_TIER),
            version=_text(data, "version", default=DEFAULT_LLAMAPARSE_VERSION),
            timeout=_float(data, "timeout", default=DEFAULT_LLAMAPARSE_TIMEOUT, minimum=1.0),
            polling_interval=_float(
                data,
                "polling_interval",
                "pollingInterval",
                default=DEFAULT_LLAMAPARSE_POLLING_INTERVAL,
                minimum=0.1,
            ),
            max_interval=_float(data, "max_interval", "maxInterval", default=DEFAULT_LLAMAPARSE_MAX_INTERVAL, minimum=0.1),
            image_download_timeout=_float(
                data,
                "image_download_timeout",
                "imageDownloadTimeout",
                default=DEFAULT_LLAMAPARSE_IMAGE_DOWNLOAD_TIMEOUT,
                minimum=1.0,
            ),
            image_categories=_text_tuple(
                data,
                "image_categories",
                "imageCategories",
                default=DEFAULT_LLAMAPARSE_IMAGE_CATEGORIES,
            ),
            ocr_languages=_text_tuple(data, "ocr_languages", "ocrLanguages", default=()),
            custom_prompt=_text(data, "custom_prompt", "customPrompt", default=DEFAULT_LLAMAPARSE_CUSTOM_PROMPT),
        )


@dataclass(frozen=True, slots=True)
class RagConfig:
    root_dir: Path = DEFAULT_RAG_ROOT
    index_root: Path = DEFAULT_RAG_INDEX_ROOT
    image_root: Path = DEFAULT_RAG_IMAGE_ROOT
    collections: RagCollectionsConfig = field(default_factory=RagCollectionsConfig)
    build: RagBuildConfig = field(default_factory=RagBuildConfig)
    chunking: RagChunkingConfig = field(default_factory=RagChunkingConfig)
    embedding: RagEmbeddingConfig = field(default_factory=RagEmbeddingConfig)
    image_embedding: RagImageEmbeddingConfig = field(default_factory=RagImageEmbeddingConfig)
    retrieval: RagRetrievalConfig = field(default_factory=RagRetrievalConfig)
    llamaparse: RagLlamaParseConfig = field(default_factory=RagLlamaParseConfig)

    @classmethod
    def from_mapping(cls, value: object) -> RagConfig:
        data = _mapping(value)
        root_dir = _path(data, "root_dir", "rootDir", default=DEFAULT_RAG_ROOT)
        return cls(
            root_dir=root_dir,
            index_root=_path(data, "index_root", "indexRoot", default=root_dir / "indexes"),
            image_root=_path(data, "image_root", "imageRoot", default=root_dir / "images"),
            collections=RagCollectionsConfig.from_mapping(data.get("collections")),
            build=RagBuildConfig.from_mapping(data.get("build")),
            chunking=RagChunkingConfig.from_mapping(data.get("chunking")),
            embedding=RagEmbeddingConfig.from_mapping(data.get("embedding")),
            image_embedding=RagImageEmbeddingConfig.from_mapping(
                data.get("image_embedding", data.get("imageEmbedding"))
            ),
            retrieval=RagRetrievalConfig.from_mapping(data.get("retrieval")),
            llamaparse=RagLlamaParseConfig.from_mapping(data.get("llamaparse")),
        )

    def safe_index_key(self, value: object = "") -> str:
        return safe_index_key(value)

    def qdrant_storage_path(self, index_key: object = DEFAULT_INDEX_KEY) -> Path:
        return self.index_root / self.safe_index_key(index_key) / "qdrant"

    def bm25_storage_path(self, index_key: object = DEFAULT_INDEX_KEY) -> Path:
        return self.index_root / self.safe_index_key(index_key) / "bm25"

    def image_output_path(self, index_key: object = DEFAULT_INDEX_KEY, *, loader: str = "llamaparse") -> Path:
        return self.image_root / self.safe_index_key(index_key) / self.safe_index_key(loader)

    def text_collection_name(self, index_key: object = DEFAULT_INDEX_KEY) -> str:
        return self._collection_name(self.collections.text, index_key)

    def image_collection_name(self, index_key: object = DEFAULT_INDEX_KEY) -> str:
        return self._collection_name(self.collections.image, index_key)

    def _collection_name(self, base: str, index_key: object) -> str:
        key = self.safe_index_key(index_key).replace("-", "_").replace(".", "_")
        return base if key == DEFAULT_INDEX_KEY else f"{base}_{key}"


@dataclass(frozen=True, slots=True)
class AppConfig:
    data: dict[str, Any]
    path: Path | None
    server: ServerConfig | None = None
    context_management: ContextManagementConfig | None = None
    context_collapse: ContextCollapseConfig | None = None
    context_compaction: ContextCompactionConfig | None = None
    tool_output: ToolOutputConfig | None = None
    library: LibraryConfig | None = None
    rag: RagConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "server", self.server or ServerConfig.from_mapping(self.data.get("server")))
        object.__setattr__(
            self,
            "context_management",
            self.context_management or ContextManagementConfig.from_mapping(self.data.get("context_management")),
        )
        object.__setattr__(
            self,
            "context_collapse",
            self.context_collapse or ContextCollapseConfig.from_mapping(self.data.get("context_collapse")),
        )
        object.__setattr__(
            self,
            "context_compaction",
            self.context_compaction or ContextCompactionConfig.from_mapping(self.data.get("context_compaction")),
        )
        object.__setattr__(self, "tool_output", self.tool_output or ToolOutputConfig.from_mapping(self.data.get("tool_output")))
        object.__setattr__(self, "library", self.library or LibraryConfig.from_mapping(self.data.get("library")))
        object.__setattr__(self, "rag", self.rag or RagConfig.from_mapping(self.data.get("rag")))

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def load_app_config(path: str | Path | None = None) -> AppConfig:
    config_path = _resolve_config_path(path)
    data = _read_json_object(config_path) if config_path.exists() else {}
    return AppConfig(data=data, path=config_path)


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    env_path = os.getenv("PAPER_NOTES_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return CONFIG_PATH


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON config: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON config must be an object: {path}")
    return payload


def safe_index_key(value: object = "") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(".-")
    return text or DEFAULT_INDEX_KEY


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _tool_limits(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    limits: dict[str, int] = {}
    for tool_name, limit in value.items():
        name = str(tool_name or "").strip()
        if not name:
            continue
        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            limits[name] = parsed
    return limits


def _pick(data: dict[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _text(data: dict[str, Any], *keys: str, default: str) -> str:
    value = _pick(data, *keys, default=default)
    text = str(value or "").strip()
    return text or default


def _bool(data: dict[str, Any], *keys: str, default: bool) -> bool:
    value = _pick(data, *keys, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int(
    data: dict[str, Any],
    *keys: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = _pick(data, *keys, default=default)
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _float(
    data: dict[str, Any],
    *keys: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _pick(data, *keys, default=default)
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _path(data: dict[str, Any], *keys: str, default: str | Path) -> Path:
    value = _pick(data, *keys, default=default)
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _text_tuple(data: dict[str, Any], *keys: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = _pick(data, *keys, default=default)
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return default


def _float_pair(data: dict[str, Any], *keys: str, default: tuple[float, float]) -> tuple[float, float]:
    value = _pick(data, *keys, default=default)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return default
    return default


def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return max(minimum, min(default, maximum))
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(result, maximum))
