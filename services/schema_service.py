"""Schema extraction & table preview. Never hardcodes any schema."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from database.metadata_models import (
    ColumnInfo, ForeignKeyInfo, SchemaSnapshot, TableInfo,
)
from utils.exceptions import QueryMateError, SchemaExtractionError
from utils.security import scrub


def extract_schema(engine: Engine, database_name: str, dialect: str) -> SchemaSnapshot:
    """Read tables, columns, PKs, FKs from the live database."""
    try:
        insp = inspect(engine)
        tables: list[TableInfo] = []
        names = [(n, False) for n in sorted(insp.get_table_names())]
        try:
            names += [(n, True) for n in sorted(insp.get_view_names())]
        except Exception:
            pass  # views are optional
        for name, is_view in names:
            pk_cols: tuple[str, ...] = ()
            fks: list[ForeignKeyInfo] = []
            if not is_view:
                pk_cols = tuple(insp.get_pk_constraint(name).get("constrained_columns") or ())
                for fk in insp.get_foreign_keys(name):
                    if fk.get("referred_table") and fk.get("constrained_columns"):
                        fks.append(ForeignKeyInfo(
                            table=name,
                            columns=tuple(fk["constrained_columns"]),
                            ref_table=fk["referred_table"],
                            ref_columns=tuple(fk.get("referred_columns") or ()),
                        ))
            fk_cols = {c for fk in fks for c in fk.columns}
            cols = tuple(
                ColumnInfo(
                    name=c["name"],
                    data_type=str(c["type"]),
                    nullable=bool(c.get("nullable", True)),
                    is_primary_key=c["name"] in pk_cols,
                    is_foreign_key=c["name"] in fk_cols,
                )
                for c in insp.get_columns(name)
            )
            tables.append(TableInfo(name, cols, pk_cols, tuple(fks), is_view))
        return SchemaSnapshot(database_name, dialect, tuple(tables))
    except SQLAlchemyError as e:
        raise SchemaExtractionError(f"Could not read the database schema: {scrub(str(getattr(e, 'orig', e)))[:300]}") from e


def _quote(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def preview_table(engine: Engine, schema: SchemaSnapshot, table: str, limit: int = 25) -> pd.DataFrame:
    """Return the first `limit` rows. The table name must exist in the snapshot (no injection)."""
    info = schema.table(table)
    if info is None:
        raise QueryMateError(f"Unknown table: {table}")
    limit = max(1, min(int(limit), 500))
    sql = f"SELECT * FROM {_quote(engine, info.name)} LIMIT {limit}"
    try:
        with engine.connect().execution_options(no_parameters=True) as conn:
            res = conn.exec_driver_sql(sql)
            return pd.DataFrame(res.fetchall(), columns=list(res.keys()))
    except SQLAlchemyError as e:
        raise QueryMateError(f"Could not preview table: {scrub(str(getattr(e, 'orig', e)))[:300]}") from e


def count_rows(engine: Engine, schema: SchemaSnapshot, table: str) -> int | None:
    info = schema.table(table)
    if info is None:
        return None
    try:
        with engine.connect().execution_options(no_parameters=True) as conn:
            return int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM {_quote(engine, info.name)}").scalar() or 0)
    except SQLAlchemyError:
        return None
