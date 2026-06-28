"""Plain terminal console entry for WireForge."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from console.terminal import main


if __name__ == "__main__":
    raise SystemExit(main())
