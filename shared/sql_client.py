import logging
import os
from typing import Any, List, Dict, Iterable

import pyodbc
# pandas imported lazily inside methods that need it
from shared.config import (
    AZSQL_SERVER,
    AZSQL_DB,
    AZSQL_DRIVER,
    AZSQL_UID,
    AZSQL_PWD,
)

class SqlClient:
    def __init__(self):
        self.server = AZSQL_SERVER
        self.db = AZSQL_DB
        self.driver = AZSQL_DRIVER if AZSQL_DRIVER else "{ODBC Driver 18 for SQL Server}"
        self.uid = AZSQL_UID
        self.pwd = AZSQL_PWD

    def _conn(self):
        # First, try Managed Identity/EntraID
        try:
            logging.info("Attempting MSI/EntraID authentication to database: %s on server %s", self.db, self.server)
            conn_str_msi = (
                f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
                "Authentication=ActiveDirectoryMsi;"
            )
            return pyodbc.connect(conn_str_msi)
        except pyodbc.Error as ex_msi:
            logging.error("Managed Identity authentication failed: %s", ex_msi)
            # Try fallback: SQL username/password authentication
            try:
                logging.info("Attempting SQL username/password authentication as fallback.")
                conn_str_sql = (
                    f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
                    f"UID={self.uid};PWD={self.pwd};"
                    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
                )
                return pyodbc.connect(conn_str_sql)
            except pyodbc.Error as ex_sql:
                logging.error("SQL username/password authentication failed: %s", ex_sql)
                # Optionally, raise the original Managed Identity error, or both
                raise Exception(
                    f"Both Managed Identity and SQL authentication failed:\n"
                    f"MSI error: {ex_msi}\nSQL auth error: {ex_sql}"
                )

    def execute(self, sql: str, params: List[Any] = None) -> int:
        logging.info("Executing execute: %s...", sql[:100])
        try:
            with self._conn() as cn:
                cur = cn.cursor()
                cur.execute(sql, params or [])
                rowcount = cur.rowcount
                cn.commit()
                logging.info("Executed statement successfully. Rows affected: %d", rowcount)
                return rowcount
        except Exception as e:
            logging.error("Error in execute: %s", e)
            raise

    def fetch_one(self, sql: str, params: List[Any] = None) -> Dict[str, Any] | None:
        logging.info("Executing fetch_one: %s...", sql[:100])
        try:
            with self._conn() as cn:
                cur = cn.cursor()
                cur.execute(sql, params or [])
                if not cur.description:
                    cn.commit()
                    logging.info("Executed a non-query statement successfully.")
                    return None
                cols = [c[0] for c in cur.description]
                row = cur.fetchone()
                logging.info("fetch_one found %s.", 'a row' if row else 'no rows')
                return None if not row else {k: v for k, v in zip(cols, row)}
        except pyodbc.Error as ex:
            logging.error("Database error in fetch_one: %s", ex)
            raise
        except Exception as e:
            logging.error("An unexpected error occurred in fetch_one: %s", e)
            raise

    def iter_query(self, sql: str, params: List[Any] = None, chunksize: int = 1000) -> Iterable[list[dict]]:
        import pandas as pd
        logging.info("Executing iter_query: %s...", sql[:100])
        try:
            with self._conn() as cn:
                for chunk in pd.read_sql(sql, cn, params=params or [], chunksize=chunksize):
                    yield chunk.to_dict(orient="records")
            logging.info("iter_query completed successfully.")
        except pyodbc.Error as ex:
            logging.error("Database error in iter_query: %s", ex)
            raise
        except Exception as e:
            logging.error("An unexpected error occurred in iter_query: %s", e)
            raise