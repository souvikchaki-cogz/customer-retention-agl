import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List

import pyodbc

# pandas imported lazily inside iter_query (unchanged — preserves original behaviour)
from shared.config import (
    AZSQL_DB,
    AZSQL_DRIVER,
    AZSQL_PWD,
    AZSQL_SERVER,
    AZSQL_UID,
)

pyodbc.pooling = True

_driver  = AZSQL_DRIVER if AZSQL_DRIVER else "{ODBC Driver 18 for SQL Server}"
_server  = AZSQL_SERVER
_db      = AZSQL_DB
_uid     = AZSQL_UID
_pwd     = AZSQL_PWD

_CONN_STR_MSI: str = (
    f"DRIVER={_driver};SERVER={_server};DATABASE={_db};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    "Authentication=ActiveDirectoryMsi;"
)

_CONN_STR_SQL: str = (
    f"DRIVER={_driver};SERVER={_server};DATABASE={_db};"
    f"UID={_uid};PWD={_pwd};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)

_SQL_AUTH_AVAILABLE: bool = bool(_uid and _pwd)

_conn_cache: Dict[str, pyodbc.Connection] = {}   # key: "msi" | "sql"
_conn_lock  = threading.Lock()


def _open_connection(use_msi: bool) -> pyodbc.Connection:
    """Open a fresh physical connection using the pre-built connection string."""
    if use_msi:
        logging.info(
            "Opening new MSI/EntraID connection to database '%s' on server '%s'.",
            _db, _server,
        )
        return pyodbc.connect(_CONN_STR_MSI)
    else:
        logging.info(
            "Opening new SQL-auth connection to database '%s' on server '%s'.",
            _db, _server,
        )
        return pyodbc.connect(_CONN_STR_SQL)


def _is_connection_alive(cn: pyodbc.Connection) -> bool:
    """
    Probe whether a cached connection is still usable.
    getinfo(SQL_DATABASE_NAME) is a driver-level call that doesn't touch the
    network if the connection is healthy, and raises if it is broken.
    """
    try:
        cn.getinfo(pyodbc.SQL_DATABASE_NAME)
        return True
    except Exception:
        return False


def _get_cached_connection(use_msi: bool) -> pyodbc.Connection:
    """
    Return a live connection from the module-level cache, creating or
    replacing it if necessary.  Thread-safe via _conn_lock.
    """
    cache_key = "msi" if use_msi else "sql"
    with _conn_lock:
        cn = _conn_cache.get(cache_key)
        if cn is None or not _is_connection_alive(cn):
            if cn is not None:
                logging.warning(
                    "Cached connection (key='%s') is no longer alive — replacing.", cache_key
                )
                try:
                    cn.close()
                except Exception:
                    pass   # best-effort close; ignore errors on a dead connection
            cn = _open_connection(use_msi)
            _conn_cache[cache_key] = cn
            logging.info("Connection cached under key='%s'.", cache_key)
        return cn


class SqlClient:
    """
    Thin SQL client for Azure SQL Database.

    Public API (unchanged from original):
        execute(sql, params)   → int   (rows affected)
        fetch_one(sql, params) → dict | None
        iter_query(sql, params, chunksize) → Iterable[list[dict]]

    Performance improvements over the original implementation:
        1. ODBC connection pooling enabled at module level (pyodbc.pooling = True).
        2. Connection strings pre-built once at import time (no per-call f-strings).
        3. Auth strategy resolved once at import time — no MSI timeout penalty in
           local dev when SQL credentials are available.
        4. Module-level connection cache: a single live connection is shared across
           all SqlClient instances and reused across calls.  A health probe
           transparently replaces dead connections.
        5. execute() and fetch_one() borrow the shared connection inside an
           explicit transaction bracket (BEGIN / COMMIT or ROLLBACK), releasing
           it back to the pool/cache immediately after each statement.
    """

    def __init__(self) -> None:
        pass

    @property
    def server(self) -> str:
        return _server

    @property
    def db(self) -> str:
        return _db

    @property
    def driver(self) -> str:
        return _driver

    @property
    def uid(self) -> str:
        return _uid

    @property
    def pwd(self) -> str:
        return _pwd

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> pyodbc.Connection:
        """
        Return a live connection.

        FIX 2 + 3: Auth mode is resolved from module-level constants (no per-call
        MSI timeout in local dev).  The connection is served from the module-level
        cache so repeated _conn() calls are cheap.

        Original fallback logic is fully preserved:
          - MSI is tried when SQL credentials are not explicitly provided.
          - SQL username/password is the primary path when AZSQL_UID/PWD are set.
          - If MSI fails, SQL auth is attempted as the fallback.
          - If both fail, a combined error is raised (identical message to original).
        """
        if _SQL_AUTH_AVAILABLE:
            try:
                return _get_cached_connection(use_msi=False)
            except pyodbc.Error as ex_sql:
                logging.error("SQL username/password authentication failed: %s", ex_sql)
                raise

        # No SQL credentials — try MSI first, fall back to SQL auth.
        try:
            return _get_cached_connection(use_msi=True)
        except pyodbc.Error as ex_msi:
            logging.error("Managed Identity authentication failed: %s", ex_msi)
            if _uid or _pwd:
                # Partial credentials present — attempt SQL auth fallback.
                try:
                    logging.info("Attempting SQL username/password authentication as fallback.")
                    return _get_cached_connection(use_msi=False)
                except pyodbc.Error as ex_sql:
                    logging.error("SQL username/password authentication failed: %s", ex_sql)
                    raise Exception(
                        f"Both Managed Identity and SQL authentication failed:\n"
                        f"MSI error: {ex_msi}\nSQL auth error: {ex_sql}"
                    )
            raise Exception(
                f"Both Managed Identity and SQL authentication failed:\n"
                f"MSI error: {ex_msi}\nSQL auth error: No SQL credentials configured."
            )

    @contextmanager
    def _transaction(self):
        """
        FIX 5 — Explicit transaction context manager.

        Yields the shared connection with autocommit=False.  On success the
        transaction is committed; on any exception it is rolled back and the
        exception is re-raised.

        Using an explicit COMMIT/ROLLBACK (rather than relying on the `with
        pyodbc.connect() as cn:` context manager, which only calls cn.commit()
        on __exit__) ensures correctness when the same connection object is
        reused across multiple calls.
        """
        cn = self._conn()
        try:
            yield cn
            cn.commit()
        except Exception:
            try:
                cn.rollback()
            except Exception as rb_err:
                logging.warning("Rollback failed: %s", rb_err)
            raise

    def execute(self, sql: str, params: List[Any] = None) -> int:
        """
        Execute a DML statement (INSERT / UPDATE / DELETE).
        Returns the number of rows affected.

        Behaviour preserved from original:
          - Logs the first 100 chars of the SQL before execution.
          - Commits after execution.
          - Logs rows affected on success.
          - Re-raises any exception after logging.
        """
        logging.info("Executing execute: %s...", sql[:100])
        try:
            with self._transaction() as cn:
                cur = cn.cursor()
                cur.execute(sql, params or [])
                rowcount = cur.rowcount
            logging.info("Executed statement successfully. Rows affected: %d", rowcount)
            return rowcount
        except Exception as e:
            logging.error("Error in execute: %s", e)
            raise

    def fetch_one(self, sql: str, params: List[Any] = None) -> Dict[str, Any] | None:
        """
        Execute a query and return the first row as a dict, or None.

        Behaviour preserved from original:
          - Logs the first 100 chars of the SQL before execution.
          - If the statement produces no result set (e.g. an INSERT passed
            through fetch_one by existing callers), commits and returns None —
            identical to the original behaviour.
          - Maps column names to values; returns None when no rows match.
          - Distinguishes pyodbc.Error from generic Exception in error logging.
          - Re-raises any exception after logging.
        """
        logging.info("Executing fetch_one: %s...", sql[:100])
        try:
            with self._transaction() as cn:
                cur = cn.cursor()
                cur.execute(sql, params or [])
                if not cur.description:
                    logging.info("Executed a non-query statement successfully.")
                    return None
                cols = [c[0] for c in cur.description]
                row = cur.fetchone()
            logging.info("fetch_one found %s.", "a row" if row else "no rows")
            return None if not row else {k: v for k, v in zip(cols, row)}
        except pyodbc.Error as ex:
            logging.error("Database error in fetch_one: %s", ex)
            raise
        except Exception as e:
            logging.error("An unexpected error occurred in fetch_one: %s", e)
            raise

    def fetch_all(self, sql: str, params: List[Any] = None) -> List[Dict[str, Any]]:
        """
        Execute a query and return all rows as a list of dicts.
        Returns an empty list when no rows match or the statement produces no result set.
        Re-raises any exception after logging.
        """
        logging.info("Executing fetch_all: %s...", sql[:100])
        try:
            with self._transaction() as cn:
                cur = cn.cursor()
                cur.execute(sql, params or [])
                if not cur.description:
                    logging.info("fetch_all: statement produced no result set.")
                    return []
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
            logging.info("fetch_all returned %d row(s).", len(rows))
            return [{k: v for k, v in zip(cols, row)} for row in rows]
        except pyodbc.Error as ex:
            logging.error("Database error in fetch_all: %s", ex)
            raise
        except Exception as e:
            logging.error("An unexpected error occurred in fetch_all: %s", e)
            raise

    def iter_query(
        self,
        sql: str,
        params: List[Any] = None,
        chunksize: int = 1000,
    ) -> Iterable[list[dict]]:
        """
        Execute a SELECT and yield results as lists of dicts in chunks.

        Behaviour preserved from original:
          - pandas imported lazily (only when this method is called).
          - Yields one list[dict] per chunk of `chunksize` rows.
          - Logs completion after all chunks are yielded.
          - Distinguishes pyodbc.Error from generic Exception in error logging.
          - Re-raises any exception after logging.

        Note: iter_query uses the shared connection directly (not _transaction)
        because the generator must keep the connection open across yields.
        The connection is not committed here — reads don't need a commit, and
        the shared connection will be reused by subsequent calls.
        """
        import pandas as pd

        logging.info("Executing iter_query: %s...", sql[:100])
        try:
            cn = self._conn()
            for chunk in pd.read_sql(sql, cn, params=params or [], chunksize=chunksize):
                yield chunk.to_dict(orient="records")
            logging.info("iter_query completed successfully.")
        except pyodbc.Error as ex:
            logging.error("Database error in iter_query: %s", ex)
            raise
        except Exception as e:
            logging.error("An unexpected error occurred in iter_query: %s", e)
            raise