"""Shared test fixtures for core module tests."""

import sys
from pathlib import Path

# Ensure core/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
