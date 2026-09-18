from __future__ import annotations

import sys
from pathlib import Path


repo_root = Path(__file__).resolve().parent.parent
source_root = repo_root / "src"
if source_root.is_dir():
    sys.path.insert(0, str(source_root))

from pyvpn.windows_gui import main


if __name__ == "__main__":
    raise SystemExit(main())
