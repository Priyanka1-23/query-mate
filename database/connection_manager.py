"""Connection lifecycle: test, save (encrypted), build read-only engines, cache schema context.

Every query path receives an explicit ConnectionContext. There is no global "current DB".
"""
from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from database.metadata_models import SavedConnection, SchemaSnapshot, make_session_factory
from database.sample_database import ensure_sample_sqlite
from services.schema_service import extract_schema
from utils import config
from utils.exceptions import ConnectionFailedError, QueryMateError
from utils.security import decrypt_secret, encrypt_secret, scrub

_WRITE_PRIVS = re.compile(
    r"\b(ALL PRIVILEGES|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|FILE|SUPER|GRANT OPTION)\b", re.I)


@dataclass(frozen=True)
class ConnectionParams:
    name: str
    host: str
    port: int
    database: str
    username: str
    password: str = ""
    dialect: str = "mysql"

    def validate(self) -> None:
        missing = [f for f, v in (("Connection name", self.name), ("Host", self.host),
                                  ("Database name", self.database), ("Username", self.username)) if not str(v).strip()]
        if missing:
            raise ConnectionFailedError(f"Please fill in: {', '.join(missing)}.")
        if not (1 <= int(self.port) <= 65535):
            raise ConnectionFailedError("Port must be between 1 and 65535.")


@dataclass(frozen=True)
class ConnectionInfo:
    id: str
    name: str
    dialect: str
    database: str
    host: str
    is_sample: bool = False


@dataclass
class ConnectionContext:
    """Everything needed to talk to ONE database. Passed explicitly into services."""
    connection_id: str
    name: str
    dialect: str
    engine: Engine
    schema: SchemaSnapshot
    warnings: tuple[str, ...] = ()


def _mysql_url(p: ConnectionParams) -> URL:
    return URL.create("mysql+pymysql", username=p.username, password=p.password or None,
                      host=p.host, port=int(p.port), database=p.database)


def _friendly_db_error(e: Exception, password: str = "") -> str:
    orig = getattr(e, "orig", e)
    code = orig.args[0] if getattr(orig, "args", None) and isinstance(orig.args[0], int) else None
    msg = {
        1045: "Access denied: check the username and password.",
        1044: "Access denied for this user on that database.",
        1049: "That database does not exist on the server.",
        2003: "Cannot reach the database server: check host and port.",
        2002: "Cannot reach the database server: check host and port.",
        2005: "Unknown host: check the host name.",
        2013: "Lost connection to the server while connecting.",
    }.get(code)
    if msg:
        return msg
    return scrub(str(orig), (password,))[:300] or "Unexpected database error."


def _build_mysql_engine(p: ConnectionParams, timeout: int, pooled: bool = True) -> Engine:
    kwargs = dict(connect_args={"connect_timeout": 10, "read_timeout": timeout + 5, "write_timeout": timeout + 5})
    if pooled:
        kwargs.update(pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800)
    else:
        kwargs["poolclass"] = NullPool
    eng = create_engine(_mysql_url(p), **kwargs)

    @event.listens_for(eng, "connect")
    def _ro(dbapi_conn, _rec):  # second layer: session is read-only even if the account could write
        cur = dbapi_conn.cursor()
        try:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        except Exception:
            pass
        finally:
            cur.close()

    return eng


def _build_sqlite_ro_engine(path: str) -> Engine:
    def creator():
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

    eng = create_engine("sqlite://", creator=creator)

    @event.listens_for(eng, "connect")
    def _ro(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA query_only = ON")

    return eng


class ConnectionManager:
    def __init__(self, metadata_url: str | None = None, sample_path=None, timeout: int = 30):
        self._lock = threading.RLock()
        self._meta_engine, self._Session = make_session_factory(metadata_url or config.metadata_url())
        self._sample_path = sample_path or config.SAMPLE_DB_PATH
        self._timeout = timeout
        self._contexts: dict[str, ConnectionContext] = {}

    # ---- sessions for other services ------------------------------------ #
    @property
    def session_factory(self):
        return self._Session

    # ---- listing ---------------------------------------------------------- #
    def list_connections(self) -> list[ConnectionInfo]:
        out = [ConnectionInfo(config.SAMPLE_CONNECTION_ID, "Sample E-commerce", "sqlite", "sample_ecommerce", "local file", True)]
        with self._Session() as s:
            for r in s.query(SavedConnection).order_by(SavedConnection.connection_name):
                out.append(ConnectionInfo(f"db-{r.id}", r.connection_name, r.database_type, r.database_name, r.host))
        return out

    def get_info(self, connection_id: str) -> ConnectionInfo | None:
        return next((c for c in self.list_connections() if c.id == connection_id), None)

    # ---- test / save / delete -------------------------------------------- #
    def test_connection(self, p: ConnectionParams) -> list[str]:
        """Raise ConnectionFailedError on failure. Returns privilege warnings."""
        p.validate()
        eng = _build_mysql_engine(p, self._timeout, pooled=False)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
                warnings = self._check_privileges(conn)
            return warnings
        except SQLAlchemyError as e:
            raise ConnectionFailedError(_friendly_db_error(e, p.password)) from e
        except Exception as e:  # driver-level errors (e.g. socket)
            raise ConnectionFailedError(_friendly_db_error(e, p.password)) from e
        finally:
            eng.dispose()

    @staticmethod
    def _check_privileges(conn) -> list[str]:
        try:
            grants = [str(r[0]) for r in conn.execute(text("SHOW GRANTS FOR CURRENT_USER()")).fetchall()]
        except Exception:
            return ["Could not verify account privileges. Use a read-only database user."]
        risky = [g for g in grants if _WRITE_PRIVS.search(g.split(" ON ")[0])]
        if risky:
            return ["This account has write privileges. QueryMate validates every query and uses read-only "
                    "sessions, but you should connect with a SELECT-only user for full protection."]
        return []

    def save_connection(self, p: ConnectionParams) -> str:
        p.validate()
        with self._Session() as s:
            if s.query(SavedConnection).filter_by(connection_name=p.name.strip()).first():
                raise QueryMateError("A connection with this name already exists.")
            row = SavedConnection(
                connection_name=p.name.strip(), database_type=p.dialect, host=p.host.strip(), port=int(p.port),
                database_name=p.database.strip(), username=p.username.strip(),
                encrypted_secret_reference=encrypt_secret(p.password or ""),
            )
            s.add(row)
            s.commit()
            return f"db-{row.id}"

    def delete_connection(self, connection_id: str) -> None:
        if connection_id == config.SAMPLE_CONNECTION_ID:
            raise QueryMateError("The sample database cannot be removed.")
        self.close(connection_id)
        rid = int(connection_id.split("-", 1)[1])
        with self._Session() as s:
            s.query(SavedConnection).filter_by(id=rid).delete()
            s.commit()

    # ---- contexts ----------------------------------------------------------- #
    def get_context(self, connection_id: str, refresh: bool = False) -> ConnectionContext:
        with self._lock:
            if refresh:
                self.close(connection_id)
            ctx = self._contexts.get(connection_id)
            if ctx is None:
                ctx = self._build_context(connection_id)
                self._contexts[connection_id] = ctx
            return ctx

    def close(self, connection_id: str) -> None:
        with self._lock:
            ctx = self._contexts.pop(connection_id, None)
            if ctx:
                ctx.engine.dispose()

    def _build_context(self, connection_id: str) -> ConnectionContext:
        if connection_id == config.SAMPLE_CONNECTION_ID:
            path = ensure_sample_sqlite(self._sample_path)
            eng = _build_sqlite_ro_engine(str(path))
            schema = extract_schema(eng, "sample_ecommerce", "sqlite")
            return ConnectionContext(connection_id, "Sample E-commerce", "sqlite", eng, schema)
        try:
            rid = int(connection_id.split("-", 1)[1])
        except Exception as e:
            raise QueryMateError("Unknown connection.") from e
        with self._Session() as s:
            row = s.get(SavedConnection, rid)
            if row is None:
                raise QueryMateError("That saved connection no longer exists.")
            p = ConnectionParams(row.connection_name, row.host, row.port, row.database_name, row.username,
                                 decrypt_secret(row.encrypted_secret_reference), row.database_type)
        eng = _build_mysql_engine(p, self._timeout)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
                warnings = tuple(self._check_privileges(conn))
            schema = extract_schema(eng, p.database, "mysql")
        except SQLAlchemyError as e:
            eng.dispose()
            raise ConnectionFailedError(_friendly_db_error(e, p.password)) from e
        except QueryMateError:
            eng.dispose()
            raise
        return ConnectionContext(connection_id, p.name, "mysql", eng, schema, warnings)

    def reset_sample(self) -> None:
        """Re-seed the sample database from scratch (fresh dates)."""
        self.close(config.SAMPLE_CONNECTION_ID)
        from database.sample_database import create_and_seed
        eng = create_engine(f"sqlite:///{self._sample_path}")
        try:
            create_and_seed(eng)
        finally:
            eng.dispose()

    def dispose_all(self) -> None:
        for cid in list(self._contexts):
            self.close(cid)
