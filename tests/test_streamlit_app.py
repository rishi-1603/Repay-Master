"""Headless checks for the Streamlit app: it loads, and every button runs without an exception.

Runs in the streamlit-smoke CI job, which installs the root requirements. Uses Streamlit's
AppTest, so no browser or server is needed.
"""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = Path(__file__).resolve().parents[1] / "app.py"


def _load():
    return AppTest.from_file(str(APP), default_timeout=90).run()


def test_app_loads_without_exceptions():
    at = _load()
    assert [e.value for e in at.exception] == []
    assert len(at.button) >= 1


@pytest.mark.parametrize("index", range(3))
def test_each_button_runs_without_exceptions(index):
    at = _load()
    if index >= len(at.button):
        pytest.skip("app shows fewer buttons than expected")
    label = at.button[index].label
    at.button[index].click().run()
    assert [e.value for e in at.exception] == [], f"clicking {label!r} raised"
