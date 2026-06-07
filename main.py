import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
UI_SRC_DIR = SRC_DIR / "ui"
for path in (SRC_DIR, UI_SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ui.backend.server import main  # noqa: E402


if __name__ == "__main__":
    main()
