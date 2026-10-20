"""Streamlit Community Cloud entry point; run from the repository root."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["NBA_CLOUD_MODE"] = "1"

# A normal import lets Streamlit track app.py and its imports when GitHub updates.
from nbaprob.app import run  # noqa: E402

run()
