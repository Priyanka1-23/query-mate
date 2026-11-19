"""Schema snapshot dataclasses (the target DB) and ORM models (QueryMate's own metadata DB)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text, Float, DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


# --------------------------------------------------------------------------- #
# Snapshot of a connected (target) database
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False


@dataclass(frozen=True)
class ForeignKeyInfo:
    table: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.table}({', '.join(self.columns)}) -> {self.ref_table}({', '.join(self.ref_columns)})"


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKeyInfo, ...] = ()
    is_view: bool = False

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


@dataclass(frozen=True)
class SchemaSnapshot:
    database_name: str
    dialect: str  # "mysql" | "sqlite"
    tables: tuple[TableInfo, ...] = ()

    def table(self, name: str) -> TableInfo | None:
        low = name.lower()
        return next((t for t in self.tables if t.name.lower() == low), None)

    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    @property
    def relationships(self) -> list[ForeignKeyInfo]:
        return [fk for t in self.tables for fk in t.foreign_keys]


# --------------------------------------------------------------------------- #
# QueryMate metadata database (ORM)
# --------------------------------------------------------------------------- #
class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SavedConnection(Base):
    __tablename__ = "saved_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_name: Mapped[str] = mapped_column(String(120), unique=True)
    database_type: Mapped[str] = mapped_column(String(20), default="mysql")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=3306)
    database_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    # Fernet-encrypted password. Never plaintext.
    encrypted_secret_reference: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class QueryHistory(Base):
    __tablename__ = "query_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # String so that the built-in sample connection ("sample") and saved ones ("db-3") fit.
    connection_id: Mapped[str] = mapped_column(String(40), index=True)
    natural_language_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_sql: Mapped[str] = mapped_column(Text)
    execution_status: Mapped[str] = mapped_column(String(20))  # success | failed
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)  # seconds
    returned_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="ask")  # ask | playground
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class SavedQuery(Base):
    __tablename__ = "saved_queries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    sql: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def make_session_factory(url: str):
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
