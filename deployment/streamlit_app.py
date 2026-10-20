"""Streamlit Community Cloud entry point; run from the repository root."""

import os
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["NBA_CLOUD_MODE"] = "1"
runpy.run_module("nbaprob.app", run_name="__main__")
