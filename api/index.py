"""Vercel entry point: runs the FastAPI backend in backend/app as one Python function.

vercel.json sends /v1/* and /health here; the web app itself is served as static files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402

__all__ = ["app"]
