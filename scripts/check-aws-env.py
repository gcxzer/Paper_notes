#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

REQUIRED_ENV = [
    "AWS_PROFILE",
    "AWS_REGION",
]

CLOUD_SYNC_ENV = [
    "PAPER_NOTES_BUCKET",
    "PAPER_NOTES_METADATA_TABLE",
    "PAPER_NOTES_KNOWLEDGE_BASE_ID",
    "PAPER_NOTES_KB_DATA_SOURCE_ID",
]


def main() -> int:
    if not ENV_PATH.exists():
        print("Missing .env. Create it with: cp .env.example .env", file=sys.stderr)
        return 1

    load_dotenv(ENV_PATH)
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    chat_backend = (os.getenv("PAPER_NOTES_CHAT_BACKEND") or "agentcore").strip().lower()
    cloud_sync_disabled = os.getenv("PAPER_NOTES_DISABLE_CLOUD_SYNC") == "1"
    if not cloud_sync_disabled:
        missing.extend(name for name in CLOUD_SYNC_ENV if not os.getenv(name))
    if chat_backend in {"agentcore", "harness"} and not os.getenv("PAPER_NOTES_AGENTCORE_HARNESS_ARN"):
        missing.append("PAPER_NOTES_AGENTCORE_HARNESS_ARN")
    if chat_backend in {"knowledge-base", "knowledge_base", "kb"} and not os.getenv("PAPER_NOTES_GENERATION_MODEL_ARN"):
        missing.append("PAPER_NOTES_GENERATION_MODEL_ARN")
    if missing:
        print("Missing required .env values:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        return 1

    warnings = []
    if chat_backend in {"agentcore", "harness"}:
        if not os.getenv("PAPER_NOTES_AGENTCORE_GATEWAY_ID") and not os.getenv("PAPER_NOTES_AGENTCORE_GATEWAY_ARN"):
            warnings.append("PAPER_NOTES_AGENTCORE_GATEWAY_ID is not set. Gateway tools may not be available.")
        if not os.getenv("PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN"):
            warnings.append("PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN is not set. The MCP deployment/target helpers need it.")
        if not os.getenv("PAPER_NOTES_MEMORY_ACTOR_ID"):
            warnings.append("PAPER_NOTES_MEMORY_ACTOR_ID is not set. Harness Memory, if attached, will not be user-scoped.")
    if not os.getenv("TAVILY_API_KEY") and not os.getenv("BRAVE_SEARCH_API_KEY"):
        warnings.append("No web search key is set. The MCP web_search tool will return a configuration error.")

    profile = os.environ["AWS_PROFILE"]
    region = os.environ["AWS_REGION"]
    print(f"Loaded .env for AWS profile {profile!r} in {region!r}.")

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        identity = session.client("sts").get_caller_identity()
    except ProfileNotFound:
        print(f"AWS profile {profile!r} was not found. Run: aws configure sso --profile {profile}", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError) as error:
        print(f"Could not call STS with profile {profile!r}: {error}", file=sys.stderr)
        print(f"If this is an SSO profile, run: aws sso login --profile {profile}", file=sys.stderr)
        return 1

    print(f"AWS identity OK: account={identity.get('Account')} arn={identity.get('Arn')}")
    for warning in warnings:
        print(f"Warning: {warning}")
    print("Paper Notes AWS environment looks ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
