import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import Store  # noqa: E402
from fake_model import FakeLLM  # noqa: E402


@pytest.fixture
def store():
    return Store(":memory:")


@pytest.fixture
def llm():
    return FakeLLM()
