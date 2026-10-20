"""Streamlit Community Cloud entry point; run from the repository root."""

import os
import sys
from pathlib import Path

source_directory = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, source_directory)
# Streamlit's source watcher checks PYTHONPATH, not runtime sys.path additions.
# src is outside this entrypoint's deployment/ directory, so register it too.
python_paths = list(filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)))
if source_directory not in python_paths:
    os.environ["PYTHONPATH"] = os.pathsep.join([source_directory, *python_paths])
os.environ["NBA_CLOUD_MODE"] = "1"

# A normal import lets Streamlit track app.py and its imports when GitHub updates.
from nbaprob.app import run  # noqa: E402

run()
