"""Unified Azure SQL ODBC client used by webapp, functions, and batch.

Supports two authentication modes:
  1. SQL auth        – set AZSQL_UID + AZSQL_PWD  (default)
  2. Entra / MSI     – set AZSQL_USE_ENTRA=1      (no UID/PWD needed)
"""
import os
import struct
import logging
import pyodbc
import pandas as pd
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)


class SqlClient:
    """Thin wrapper around pyodbc for Azure SQL / ODBC Driver 18."""

    SQL_COPT_SS_ACCESS_TOKEN = 1256  # pyodbc connection attribute for Azure AD token

    def __init__(self):
        self.server = os.getenv("AZSQL_SERVER") or os.getenv("AZURE_SQL_SERVER", "")
        self.db = os.getenv("AZSQL_DB") or os.getenv("AZURE_SQL_DATABASE", "")
        self.uid = os.getenv("AZSQL_UID") or os.getenv("AZURE_SQL_USERNAME", "")
        self.pwd = os.getenv("AZSQL_PWD") or os.getenv("AZURE_SQL_PASSWORD", "")
        self.driver = os.getenv("AZSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
        self.use_entra = os.getenv("AZSQL_USE_ENTRA", "0") == "1"

    @property
    def is_configured(self) -> bool:
        """Return True when enough env vars are present for the chosen auth mode."""
        if self.use_entra:
            return all([self.server, self.db])
        return all([self.server, self.db, self.uid, self.pwd])

    # ------------------------------------------------------------------ #
    #  Connection                                                         #
    # ------------------------------------------------------------------ #
    def _conn(self):
        base = (
            f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )

        if self.use_entra:
            token_struct = self._acquire_entra_token()
            return pyodbc.connect(
                base,
                attrs_before={self.SQL_COPT_SS_ACCESS_TOKEN: token_struct},
            )
        else:
            return pyodbc.connect(base + f"UID={self.uid};PWD={self.pwd};")

    def _acquire_entra_token(self) -> bytes:
        """Acquire an Azure AD access token via DefaultAzureCredential and
        pack it into the binary struct that ODBC Driver 18 expects."""
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token = credential.get_token("https://database.windows.net/.default")
        token_bytes = token.token.encode("UTF-16-LE")
        return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    # ------------------------------------------------------------------ #
    #  Query helpers                                                      #
    # ------------------------------------------------------------------ #
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