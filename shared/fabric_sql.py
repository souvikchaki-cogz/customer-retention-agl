import os, pyodbc, pandas as pd
from typing import Any, List, Dict

class FabricClient:
    def __init__(self):
        self.server = os.getenv("FABRIC_SQL_SERVER")
        self.db = os.getenv("FABRIC_SQL_DB")
        self.uid = os.getenv("FABRIC_SQL_UID")
        self.pwd = os.getenv("FABRIC_SQL_PWD")
        self.driver = os.getenv("FABRIC_SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")

    def _conn(self):
        return pyodbc.connect(
            f"DRIVER={self.driver};SERVER={self.server};DATABASE={self.db};"
            f"UID={self.uid};PWD={self.pwd};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )

    def fetch_one(self, sql: str, params: List[Any] = None) -> Dict[str, Any] | None:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(sql, params or [])
            colnames = [c[0] for c in cur.description] if cur.description else []
            row = cur.fetchone()
            return None if not row else dict(zip(colnames, row))

    def iter_query(self, sql: str, params: List[Any] = None, chunksize: int = 1000):
        with self._conn() as cn:
            for chunk in pd.read_sql(sql, cn, params=params or [], chunksize=chunksize):
                yield chunk.to_dict(orient="records")