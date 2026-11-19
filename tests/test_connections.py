import os
import sqlite3

import pytest
from sqlalchemy import text

from database.connection_manager import ConnectionManager, ConnectionParams
from utils.exceptions import ConnectionFailedError, QueryMateError
from utils.security import decrypt_secret, encrypt_secret, scrub


def test_sample_loads_without_credentials(manager):
    infos = manager.list_connections()
    assert infos[0].is_sample and infos[0].id == "sample"
    ctx = manager.get_context("sample")
    assert ctx.dialect == "sqlite"
    assert len(ctx.schema.tables) == 6


def test_missing_fields_rejected():
    with pytest.raises(ConnectionFailedError, match="fill in"):
        ConnectionParams("", "", 3306, "", "").validate()


def test_invalid_port_rejected():
    with pytest.raises(ConnectionFailedError, match="Port"):
        ConnectionParams("x", "h", 99999, "d", "u").validate()


def test_database_unavailable_gives_friendly_error(manager):
    p = ConnectionParams("x", "127.0.0.1", 1, "db", "u", "secret-pw")
    with pytest.raises(ConnectionFailedError) as e:
        manager.test_connection(p)
    assert "secret-pw" not in str(e.value)


def test_save_encrypts_password_and_delete(manager):
    p = ConnectionParams("Prod RO", "db.example.com", 3306, "shop", "reader", "Sup3r-Secret!")
    cid = manager.save_connection(p)
    assert cid.startswith("db-")
    # plaintext must not be in the metadata DB file
    with manager._meta_engine.connect() as c:
        stored = c.execute(text("SELECT encrypted_secret_reference FROM saved_connections")).scalar()
    assert "Sup3r-Secret!" not in stored and decrypt_secret(stored) == "Sup3r-Secret!"
    assert any(i.id == cid for i in manager.list_connections())
    with pytest.raises(QueryMateError, match="already exists"):
        manager.save_connection(p)
    manager.delete_connection(cid)
    assert not any(i.id == cid for i in manager.list_connections())


def test_sample_cannot_be_deleted(manager):
    with pytest.raises(QueryMateError):
        manager.delete_connection("sample")


def test_unknown_connection(manager):
    with pytest.raises(QueryMateError):
        manager.get_context("db-99999")


def test_encrypt_roundtrip_and_scrub():
    assert decrypt_secret(encrypt_secret("hello")) == "hello"
    assert "pw123" not in scrub("mysql+pymysql://root:pw123@host/db failed", ("pw123",))
    assert "gsk_abc123" not in scrub("key gsk_abc123 bad")


@pytest.mark.skipif(not os.getenv("QUERYMATE_TEST_MYSQL_URL"), reason="set QUERYMATE_TEST_MYSQL_URL for live MySQL tests")
def test_live_mysql_invalid_credentials():
    p = ConnectionParams("t", os.getenv("QUERYMATE_TEST_MYSQL_HOST", "127.0.0.1"), 3306, "mysql", "nobody", "wrong")
    m = ConnectionManager(metadata_url="sqlite://")
    with pytest.raises(ConnectionFailedError):
        m.test_connection(p)
