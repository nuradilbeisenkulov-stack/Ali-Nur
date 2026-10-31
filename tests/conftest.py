from pathlib import Path

import pytest

from app.engine import TriageEngine
from scripts.common import resolve_data_dir


@pytest.fixture(scope="session")
def data_dir() -> Path:
    path = resolve_data_dir()
    for filename in ("rules.json", "taxonomy.json"):
        if not (path / filename).is_file():
            pytest.fail(f"Missing {filename}; configure SUPPORT_DATA_DIR before running tests.")
    return path


@pytest.fixture
def engine(data_dir):
    return TriageEngine(data_dir)


@pytest.fixture
def make_ticket():
    def make(text="Не удаётся выйти из гаража, персонаж застрял.", **overrides):
        return {"kind": "report", "lang": "ru", "messages": [{"role": "player", "text": text}], **overrides}
    return make
