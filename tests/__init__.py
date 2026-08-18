"""Tests for bd-explore."""

import sys
from pathlib import Path

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)
