"""说明：封装检索结果重排逻辑。

作用：根据配置对召回片段重新排序，提高最终提供给模型的上下文质量。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app_config.config import RagRerankingConfig
from app_infra.formatting import normalize_text

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


class RerankError(RuntimeError):
    pass


def rerank_results(query: str, results: list[Any], config: RagRerankingConfig, *, top_n: int) -> list[Any]:
    if not results or not config.enabled:
        return results[:top_n]
    if config.provider_name() != "dashscope":
        raise RerankError(f"Unsupported reranking provider: {config.provider}")

    documents, result_indexes = _documents_for_results(results, max_document_chars=config.max_document_chars)
    if not documents:
        return results[:top_n]

    payload = {
        "model": config.model,
        "input": {
            "query": {"text": query},
            "documents": documents,
        },
        "parameters": {
            "top_n": min(max(1, top_n), len(documents)),
            "return_documents": False,
        },
    }
    instruct = normalize_text(config.instruct)
    if instruct:
        payload["parameters"]["instruct"] = instruct

    ranked_indexes = _dashscope_rerank_indexes(payload, config)
    reranked = []
    used_result_indexes = set()
    for document_index, score in ranked_indexes:
        if document_index < 0 or document_index >= len(result_indexes):
            continue
        result_index = result_indexes[document_index]
        if result_index in used_result_indexes:
            continue
        result = results[result_index]
        try:
            result.score = score
        except Exception:
            pass
        reranked.append(result)
        used_result_indexes.add(result_index)
        if len(reranked) >= top_n:
            break

    if len(reranked) < top_n:
        for result_index, result in enumerate(results):
            if result_index in used_result_indexes:
                continue
            reranked.append(result)
            if len(reranked) >= top_n:
                break

    return reranked


def _documents_for_results(results: list[Any], *, max_document_chars: int) -> tuple[list[dict[str, str]], list[int]]:
    documents = []
    result_indexes = []
    for result_index, result in enumerate(results):
        text = _result_text(result)
        if not text:
            continue
        documents.append({"text": text[:max_document_chars]})
        result_indexes.append(result_index)
    return documents, result_indexes


def _result_text(result: Any) -> str:
    node = getattr(result, "node", None)
    text = ""
    if node is not None and callable(getattr(node, "get_content", None)):
        text = str(node.get_content() or "")
    metadata = dict(getattr(node, "metadata", {}) or {})
    caption_text = normalize_text(metadata.get("caption_text"))
    if caption_text and caption_text not in text:
        text = f"Original PDF caption:\n{caption_text}\n\n{text}"
    return normalize_text(text)


def _dashscope_rerank_indexes(payload: dict[str, Any], config: RagRerankingConfig) -> list[tuple[int, float]]:
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise RerankError(f"{config.api_key_env} is required for DashScope reranking.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=config.timeout) as client:
        response = client.post(config.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    if data.get("code") and not data.get("output"):
        raise RerankError(f"DashScope rerank failed: {data.get('code')}: {data.get('message', '')}")

    raw_results = data.get("output", {}).get("results")
    if raw_results is None and isinstance(data.get("results"), list):
        raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise RerankError("DashScope rerank response did not contain output.results.")

    ranked = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        try:
            score = float(item.get("relevance_score"))
        except (TypeError, ValueError):
            score = 0.0
        ranked.append((index, score))
    return ranked
