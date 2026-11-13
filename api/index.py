"""Vercel WSGI entry point for the Biri-Go Flask application."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "system" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import app  # noqa: E402,F401
