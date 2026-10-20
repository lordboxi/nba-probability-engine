"""Streamlit Community Cloud entry point; run from the repository root."""

import os
import runpy

os.environ["NBA_CLOUD_MODE"] = "1"
runpy.run_module("nbaprob.app", run_name="__main__")
