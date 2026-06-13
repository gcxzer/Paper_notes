import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


def get_embedding_model(
    provider: str = "ollama",
    model: str | None = None,
    embed_batch_size: int = 100,
):
    provider = provider.lower()

    if provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model=os.getenv("MODELSCOPE_EMBEDDING_MODEL") or "Qwen/Qwen3-Embedding-8B",
            api_base=os.getenv("MODELSCOPE_BASEURL"),
            api_key=os.getenv("MODELSCOPE_TOKEN"),
            embed_batch_size=embed_batch_size,
        )

    if provider == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model_name=model or "qwen3-embedding:8b",
            base_url="http://localhost:11434",
        )

    raise ValueError(f"Unsupported embedding provider: {provider}")


def get_image_embedding_model(model: str = "ViT-B/32"):
    from llama_index.embeddings.clip import ClipEmbedding

    return ClipEmbedding(model_name=model)
