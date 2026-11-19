import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="querymate_test_")
os.environ["QUERYMATE_DATA_DIR"] = _TMP  # must be set before utils.config is imported
os.environ.pop("QUERYMATE_SECRET_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from database.connection_manager import ConnectionManager  # noqa: E402
from services.history_service import HistoryService  # noqa: E402
from utils.config import Preferences  # noqa: E402


@pytest.fixture(scope="session")
def manager(tmp_path_factory):
    d = tmp_path_factory.mktemp("qm")
    m = ConnectionManager(metadata_url=f"sqlite:///{d}/meta.db", sample_path=d / "sample.db", timeout=5)
    yield m
    m.dispose_all()


@pytest.fixture(scope="session")
def ctx(manager):
    return manager.get_context("sample")


@pytest.fixture()
def history(manager):
    return HistoryService(manager.session_factory)


@pytest.fixture()
def prefs():
    return Preferences(result_limit=1000, query_timeout=5)
