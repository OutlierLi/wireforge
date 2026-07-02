"""Start the persistent WireForge Lab daemon."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lab_service.rpc import main


if __name__ == "__main__":
    raise SystemExit(main())
