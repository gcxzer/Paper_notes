from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

mcp = FastMCP(host="0.0.0.0", stateless_http=True)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _required_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(f"Missing required configuration {name}. Add it to the AgentCore Runtime environment.")
    return value


def _session() -> boto3.Session:
    region = _required_env("AWS_REGION")
    profile = _env("AWS_PROFILE")
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def _source_uri(location: dict[str, Any]) -> str:
    if not isinstance(location, dict):
        return ""
    s3_location = location.get("s3Location") or {}
    if isinstance(s3_location, dict) and s3_location.get("uri"):
        return str(s3_location["uri"])
    web_location = location.get("webLocation") or {}
    if isinstance(web_location, dict) and web_location.get("url"):
        return str(web_location["url"])
    return ""


def _clamp_results(max_results: int) -> int:
    try:
        value = int(max_results)
    except Exception:
        value = 5
    return min(max(value, 1), 10)


def _http_json(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, data=data, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {error.code}: {message}"}
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"error": str(error)}


def _tavily_search(query: str, max_results: int) -> dict[str, Any]:
    api_key = _required_env("TAVILY_API_KEY")
    request = Request(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": _env("PAPER_NOTES_TAVILY_SEARCH_DEPTH", "basic") or "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    data = _http_json(request, payload)
    if data.get("error"):
        return {"provider": "tavily", "query": query, "results": [], "error": data["error"]}
    return {
        "provider": "tavily",
        "query": query,
        "results": [
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("content") or "").strip(),
                "score": item.get("score"),
            }
            for item in data.get("results") or []
        ],
    }


def _brave_search(query: str, max_results: int) -> dict[str, Any]:
    api_key = _required_env("BRAVE_SEARCH_API_KEY")
    params = urlencode({"q": query, "count": max_results})
    request = Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    data = _http_json(request)
    if data.get("error"):
        return {"provider": "brave", "query": query, "results": [], "error": data["error"]}
    web_results = (data.get("web") or {}).get("results") or []
    return {
        "provider": "brave",
        "query": query,
        "results": [
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("description") or "").strip(),
                "publishedDate": item.get("age"),
            }
            for item in web_results
        ],
    }


def _web_search_provider() -> str:
    if _env("TAVILY_API_KEY"):
        return "tavily"
    if _env("BRAVE_SEARCH_API_KEY"):
        return "brave"
    return "none"


@mcp.tool()
def search_paper_notes(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the Paper Notes knowledge base and return relevant snippets with source URIs."""
    query_text = str(query or "").strip()
    if not query_text:
        return {"results": [], "error": "query is required"}

    knowledge_base_id = _required_env("PAPER_NOTES_KNOWLEDGE_BASE_ID")
    number_of_results = _clamp_results(max_results)
    client = _session().client("bedrock-agent-runtime", region_name=_required_env("AWS_REGION"))

    try:
        response = client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": number_of_results,
                }
            },
        )
    except (BotoCoreError, ClientError) as error:
        return {"results": [], "error": str(error)}

    results = []
    for item in response.get("retrievalResults") or []:
        content = item.get("content") or {}
        metadata = item.get("metadata") or {}
        location = item.get("location") or {}
        results.append(
            {
                "text": str(content.get("text") or "").strip(),
                "sourceUri": _source_uri(location),
                "score": item.get("score"),
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        )

    return {
        "query": query_text,
        "knowledgeBaseId": knowledge_base_id,
        "results": results,
    }


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the public web for recent or external information and return results with URLs."""
    query_text = str(query or "").strip()
    if not query_text:
        return {"results": [], "error": "query is required"}

    provider = _web_search_provider()
    number_of_results = _clamp_results(max_results or int(_env("PAPER_NOTES_WEB_SEARCH_MAX_RESULTS", "5") or "5"))

    try:
        if provider == "tavily":
            return _tavily_search(query_text, number_of_results)
        if provider == "brave":
            return _brave_search(query_text, number_of_results)
    except RuntimeError as error:
        return {"provider": provider, "query": query_text, "results": [], "error": str(error)}

    return {
        "provider": provider or "none",
        "query": query_text,
        "results": [],
        "error": "Web search is not configured. Set TAVILY_API_KEY or BRAVE_SEARCH_API_KEY. If both are set, Tavily is used.",
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
