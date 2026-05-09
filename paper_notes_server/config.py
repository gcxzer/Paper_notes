from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "4173"))
MAX_BODY_SIZE = int(os.getenv("PAPER_NOTES_MAX_BODY_SIZE", str(200 * 1024 * 1024)))

PAPERS_DIR = ROOT / "Papers"
HTML_DIR = ROOT / "Paper-html"
ANNOTATIONS_DIR = ROOT / "Paper-annotations"
NOTES_PATH = ROOT / "notes.json"
LOCAL_DATA_DIR = ROOT / ".paper-notes-local"
CHAT_SESSIONS_DIR = LOCAL_DATA_DIR / "sessions"
LEGACY_CHAT_SESSIONS_PATH = LOCAL_DATA_DIR / "chat-sessions.json"

AWS_REGION = os.getenv("AWS_REGION", "")
AWS_PROFILE = os.getenv("AWS_PROFILE", "")
CHAT_BACKEND = os.getenv("PAPER_NOTES_CHAT_BACKEND", "agentcore").strip().lower()
GENERATION_MODEL_ARN = os.getenv("PAPER_NOTES_GENERATION_MODEL_ARN", "")
KB_NUMBER_OF_RESULTS = int(os.getenv("PAPER_NOTES_KB_NUMBER_OF_RESULTS", "5"))
HARNESS_ARN = (
    os.getenv("PAPER_NOTES_AGENTCORE_HARNESS_ARN")
    or os.getenv("PAPER_NOTES_HARNESS_ARN")
    or ""
)
MEMORY_ACTOR_ID = os.getenv("PAPER_NOTES_MEMORY_ACTOR_ID", "")
AGENTCORE_GATEWAY_ID = os.getenv("PAPER_NOTES_AGENTCORE_GATEWAY_ID", "")
AGENTCORE_GATEWAY_ARN = os.getenv("PAPER_NOTES_AGENTCORE_GATEWAY_ARN", "")
AGENTCORE_MCP_RUNTIME_ARN = os.getenv("PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN", "")
AGENTCORE_RUNTIME_QUALIFIER = os.getenv("PAPER_NOTES_AGENTCORE_RUNTIME_QUALIFIER", "DEFAULT")
GATEWAY_TARGET_NAME = os.getenv("PAPER_NOTES_GATEWAY_TARGET_NAME", "paper-notes-mcp")
PAPER_NOTES_BUCKET = os.getenv("PAPER_NOTES_BUCKET", "")
PAPER_NOTES_METADATA_TABLE = os.getenv("PAPER_NOTES_METADATA_TABLE", "")
PAPER_NOTES_OWNER_ID = os.getenv("PAPER_NOTES_OWNER_ID", "personal")
KNOWLEDGE_BASE_ID = os.getenv("PAPER_NOTES_KNOWLEDGE_BASE_ID", "")
KNOWLEDGE_BASE_DATA_SOURCE_ID = os.getenv("PAPER_NOTES_KB_DATA_SOURCE_ID", "")
DISABLE_CLOUD_SYNC = os.getenv("PAPER_NOTES_DISABLE_CLOUD_SYNC") == "1"
