from __future__ import annotations

from app_config.secrets import LOCAL_STATE_DIR, PROJECT_ROOT


SKILLS_TOOLSET = "skills"
PAPER_NOTES_SKILLS_DIR = LOCAL_STATE_DIR / "skills"
REPO_SKILLS_DIR = PROJECT_ROOT / "src" / "skills"
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
TRUSTED_SUPPORT_DIRS = ("references", "templates", "scripts", "assets")
OTHER_SUPPORT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".tex", ".sh"}
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".js", ".ts", ".rb"}
TEXT_FILE_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".bash",
    ".tex",
    ".rb",
}
PLATFORM_MAP = {
    "macos": "darwin",
    "darwin": "darwin",
    "linux": "linux",
    "windows": "win32",
    "win32": "win32",
}
INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard your",
    "forget your instructions",
    "system prompt:",
    "<system>",
)
