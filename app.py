"""Streamlit entry point.

The app lives in app/app.py; this file only keeps `streamlit run app.py`
working (that command was in the README before the package refactor).
"""

from pathlib import Path
import runpy

APP = Path(__file__).resolve().parent / "app" / "app.py"
runpy.run_path(str(APP), run_name="__main__")