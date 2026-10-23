import importlib.util
from pathlib import Path

import pytest

DEMO_PATH = Path(__file__).parents[1] / "examples" / "synthetic_demo.py"
spec = importlib.util.spec_from_file_location("synthetic_demo", DEMO_PATH)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture
def run():
    return demo.synthetic_input(approved=True)


@pytest.fixture
def pending_run():
    return demo.synthetic_input(approved=False)
