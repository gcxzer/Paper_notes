"""说明：创建 RAG 使用的 embedding 模型。

作用：根据配置选择 provider、模型和凭据，供向量索引与查询使用。
"""

import os

from app_config import load_app_config

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


def get_embedding_model(
    provider: str | None = None,
    model: str | None = None,
    embed_batch_size: int | None = None,
):
    embedding = load_app_config().rag.embedding
    provider = embedding.provider_name(provider)
    model = embedding.model_for(provider, model)
    batch_size = embedding.batch_size_for(provider, embed_batch_size)

    if provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model_name=os.getenv("MODELSCOPE_EMBEDDING_MODEL") or model,
            api_base=os.getenv(embedding.openai.api_base_env) or embedding.openai.api_base or None,
            api_key=os.getenv(embedding.openai.api_key_env),
            embed_batch_size=batch_size,
        )

    if provider == "dashscope":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model_name=model,
            api_base=os.getenv(embedding.dashscope.api_base_env) or embedding.dashscope.api_base,
            api_key=os.getenv(embedding.dashscope.api_key_env),
            dimensions=embedding.dashscope.dimensions,
            embed_batch_size=batch_size,
        )

    if provider == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model_name=model,
            base_url=embedding.ollama.base_url,
        )

    raise ValueError(f"Unsupported embedding provider: {provider}")
