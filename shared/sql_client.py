"""SQL Client for Azure SQL Database interactions."""
import os
import logging

from typing import Any, List, Dict, Iterable

import pyodbc
import pandas as pd


class SqlClient:
    def __init__(self):
        self.server = os.getenv("AZSQL_SERVER")  # e.g. myserver.database.windows.net
        self.db = os.getenv("AZSQL_DB")
        self.uid = os.getenv("AZSQL_UID")
        self.pwd = os.getenv("AZSQL_PWD")
        self.driver = os.getenv("AZURE_SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
        self.use_entra = os.getenv("AZSQL_USE_ENTRA", "0") == "1"

    def _conn(self):
        try:
            # Log connection attempt without password
            logging.info("Attempting to connect to database: %s on server %s", self.db, self.server)
            return pyodbc.connect(
                f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};UID={self.uid};PWD={self.pwd};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
            )
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