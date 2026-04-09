"""Database adapter: wraps SQLAlchemy Session to provide asyncpg-style API.

The agent system was designed with asyncpg-style db.fetchrow/fetch/fetchval/execute.
This adapter translates those calls to SQLAlchemy's synchronous Session + text() queries,
converting $1/$2 positional params to :p1/:p2 named params.
"""

import re
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _convert_params(query: str, args: tuple) -> tuple[str, dict]:
    """Convert asyncpg-style $1, $2 positional params to SQLAlchemy :p1, :p2 named params."""
    params = {}
    for i, val in enumerate(args, 1):
        params[f"p{i}"] = val

    # Replace $N with :pN (but not inside strings)
    converted = re.sub(r'\$(\d+)', r':p\1', query)
    return converted, params


class DbAdapter:
    """Wraps a SQLAlchemy Session to provide asyncpg-compatible interface."""

    def __init__(self, session: Session):
        self._session = session

    async def fetchrow(self, query: str, *args) -> dict | None:
        """Execute query and return first row as dict, or None."""
        try:
            q, params = _convert_params(query, args)
            result = self._session.execute(text(q), params)
            row = result.mappings().first()
            if row is None:
                return None
            return dict(row)
        except Exception as e:
            logger.error("fetchrow error: %s | query: %s", e, query[:100])
            self._session.rollback()
            raise

    async def fetch(self, query: str, *args) -> list[dict]:
        """Execute query and return all rows as list of dicts."""
        try:
            q, params = _convert_params(query, args)
            result = self._session.execute(text(q), params)
            return [dict(row) for row in result.mappings().all()]
        except Exception as e:
            logger.error("fetch error: %s | query: %s", e, query[:100])
            self._session.rollback()
            raise

    async def fetchval(self, query: str, *args) -> Any:
        """Execute query and return the first column of first row."""
        try:
            q, params = _convert_params(query, args)
            result = self._session.execute(text(q), params)
            row = result.first()
            if row is None:
                return None
            return row[0]
        except Exception as e:
            logger.error("fetchval error: %s | query: %s", e, query[:100])
            self._session.rollback()
            raise

    async def execute(self, query: str, *args) -> str:
        """Execute a query (INSERT/UPDATE/DELETE) and commit."""
        try:
            q, params = _convert_params(query, args)
            self._session.execute(text(q), params)
            self._session.commit()
            return "OK"
        except Exception as e:
            logger.error("execute error: %s | query: %s", e, query[:100])
            self._session.rollback()
            raise
