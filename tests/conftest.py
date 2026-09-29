import pytest

from checker import config
from checker.core import db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Fresh data dir + database per test."""
    monkeypatch.setenv("CHECKER_DATA_DIR", str(tmp_path / "data"))
    config.get_settings.cache_clear()
    db.init_db()
    yield tmp_path / "data"
    config.get_settings.cache_clear()
    db._Session = None
