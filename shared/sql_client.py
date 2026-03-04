"""SQL Client for Azure SQL Database interactions."""
import logging
from typing import Any, List, Dict, Iterable

import pyodbc
import pandas as pd
from shared.config import (
    AZSQL_SERVER,
    AZSQL_DB,
    AZSQL_UID,
    AZSQL_PWD,
    AZSQL_DRIVER,
    AZSQL_USE_ENTRA,
)

class SqlClient:
    def __init__(self):
        self.server = AZSQL_SERVER  # unified config value
        self.db = AZSQL_DB
        self.uid = AZSQL_UID
        self.pwd = AZSQL_PWD
        self.driver = AZSQL_DRIVER if AZSQL_DRIVER else "{ODBC Driver 18 for SQL Server}"
        self.use_entra = AZSQL_USE_ENTRA == "1" if isinstance(AZSQL_USE_ENTRA, str) else bool(AZSQL_USE_ENTRA)

    def _conn(self):
        try:
            logging.info("Attempting to connect to database: %s on server %s", self.db, self.server)
            base_conn_str = (
                f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
            )
            if self.use_entra:
                conn_str = f"{base_conn_str}Authentication=ActiveDirectoryMsi;"
                logging.info("Connecting using Entra ID (Managed Identity).")
            else:
                conn_str = f"{base_conn_str}UID={self.uid};PWD={self.pwd};"

            return pyodbc.connect(conn_str)
        except pyodbc.Error as ex:
            logging.error("Database connection failed: %s", ex)
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