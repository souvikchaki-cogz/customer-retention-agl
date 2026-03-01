"""Unified Azure SQL ODBC client used by webapp, functions, and batch."""
import os
import pyodbc
import pandas as pd
from typing import Any, Dict, Iterable, List


class SqlClient:
    """Thin wrapper around pyodbc for Azure SQL / ODBC Driver 18."""

    def __init__(self):
        self.server = os.getenv("AZSQL_SERVER") or os.getenv("AZURE_SQL_SERVER", "")
        self.db = os.getenv("AZSQL_DB") or os.getenv("AZURE_SQL_DATABASE", "")
        self.uid = os.getenv("AZSQL_UID") or os.getenv("AZURE_SQL_USERNAME", "")
        self.pwd = os.getenv("AZSQL_PWD") or os.getenv("AZURE_SQL_PASSWORD", "")
        self.driver = os.getenv("AZSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")

    @property
    def is_configured(self) -> bool:
        return all([self.server, self.db, self.uid, self.pwd])

    def _conn(self):
        return pyodbc.connect(
            f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
            f"UID={self.uid};PWD={self.pwd};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )

    def fetch_one(self, sql: str, params: List[Any] | None = None) -> Dict[str, Any] | None:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(sql, params or [])
            if not cur.description:
                cn.commit()
                return None
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return None if not row else dict(zip(cols, row))

    def fetch_all(self, sql: str, params: List[Any] | None = None) -> List[Dict[str, Any]]:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(sql, params or [])
            if not cur.description:
                return []
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def execute(self, sql: str, params: List[Any] | None = None) -> int:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(sql, params or [])
            rowcount = cur.rowcount
            cn.commit()
            return rowcount

    def iter_query(self, sql: str, params: List[Any] | None = None, chunksize: int = 1000) -> Iterable[list[dict]]:
        with self._conn() as cn:
            for chunk in pd.read_sql(sql, cn, params=params or [], chunksize=chunksize):
                yield chunk.to_dict(orient="records")