"""CLI entry for the local protocol knowledge base."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge_base.store import main


if __name__ == "__main__":
    raise SystemExit(main())
