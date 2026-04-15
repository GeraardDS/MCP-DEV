"""Shared pytest fixtures and path bootstrap."""

import os
import sys

# Put repo root on sys.path so `import core.*` / `import server.*` resolves.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
