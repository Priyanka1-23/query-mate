"""Query history + saved queries, stored in QueryMate's own metadata DB (never in the analysed DB)."""
from __future__ import annotations

from sqlalchemy import func

from database.metadata_models import QueryHistory, SavedQuery


def _h(r: QueryHistory) -> dict:
    return {c.name: getattr(r, c.name) for c in QueryHistory.__table__.columns}


def _s(r: SavedQuery) -> dict:
    return {c.name: getattr(r, c.name) for c in SavedQuery.__table__.columns}


class HistoryService:
    def __init__(self, session_factory):
        self._S = session_factory

    # ------------------------------------------------------------ history
    def record(self, connection_id: str, sql: str, status: str, question: str | None = None,
               execution_time: float | None = None, row_count: int | None = None,
               error: str | None = None, source: str = "ask") -> int:
        with self._S() as s:
            row = QueryHistory(connection_id=connection_id, natural_language_question=question, generated_sql=sql,
                               execution_status=status, execution_time=execution_time, returned_row_count=row_count,
                               error_message=(error or None) and error[:500], source=source)
            s.add(row)
            s.commit()
            return row.id

    def list(self, connection_id: str | None = None, limit: int = 100, status: str | None = None,
             search: str | None = None) -> list[dict]:
        with self._S() as s:
            q = s.query(QueryHistory)
            if connection_id:
                q = q.filter(QueryHistory.connection_id == connection_id)
            if status:
                q = q.filter(QueryHistory.execution_status == status)
            if search:
                like = f"%{search}%"
                q = q.filter(QueryHistory.generated_sql.ilike(like) | QueryHistory.natural_language_question.ilike(like))
            return [_h(r) for r in q.order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc()).limit(limit)]

    def get(self, history_id: int) -> dict | None:
        with self._S() as s:
            r = s.get(QueryHistory, history_id)
            return _h(r) if r else None

    def count(self, connection_id: str | None = None, only_success: bool = False, executed_only: bool = False) -> int:
        """executed_only excludes queries rejected by validation (those never reached the database)."""
        with self._S() as s:
            q = s.query(func.count(QueryHistory.id))
            if connection_id:
                q = q.filter(QueryHistory.connection_id == connection_id)
            if only_success:
                q = q.filter(QueryHistory.execution_status == "success")
            if executed_only:
                q = q.filter(QueryHistory.execution_status != "rejected")
            return int(q.scalar() or 0)

    def recent_questions(self, connection_id: str, n: int = 5) -> list[str]:
        with self._S() as s:
            rows = (s.query(QueryHistory.natural_language_question)
                    .filter(QueryHistory.connection_id == connection_id, QueryHistory.natural_language_question.isnot(None))
                    .order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc()).limit(50).all())
        out: list[str] = []
        for (q,) in rows:
            if q and q not in out:
                out.append(q)
            if len(out) >= n:
                break
        return out

    def delete(self, history_id: int) -> None:
        with self._S() as s:
            s.query(QueryHistory).filter_by(id=history_id).delete()
            s.commit()

    def clear(self, connection_id: str) -> None:
        with self._S() as s:
            s.query(QueryHistory).filter_by(connection_id=connection_id).delete()
            s.query(SavedQuery).filter_by(connection_id=connection_id).delete()
            s.commit()

    # ------------------------------------------------------------ saved queries
    def save_query(self, connection_id: str, title: str, sql: str, description: str | None = None) -> int:
        with self._S() as s:
            row = SavedQuery(connection_id=connection_id, title=title.strip() or "Untitled query", sql=sql, description=description)
            s.add(row)
            s.commit()
            return row.id

    def list_saved(self, connection_id: str) -> list[dict]:
        with self._S() as s:
            return [_s(r) for r in s.query(SavedQuery).filter_by(connection_id=connection_id)
                    .order_by(SavedQuery.created_at.desc())]

    def delete_saved(self, saved_id: int) -> None:
        with self._S() as s:
            s.query(SavedQuery).filter_by(id=saved_id).delete()
            s.commit()
