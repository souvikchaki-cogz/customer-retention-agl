from ..shared.sql_client import SqlClient

def main(payload: dict) -> dict:
    customer_id = payload["customer_id"]
    event_ts = payload["event_ts"]

    sqlc = SqlClient()
    sql = """
    ;WITH last_snap AS (
      SELECT TOP (1)
        customer_id, rate AS current_rate, term_months,
        LAG(rate) OVER (PARTITION BY customer_id ORDER BY snapshot_ts) AS prev_rate,
        DATEDIFF(day, origination_date, ?) AS account_age_days
      FROM customers_snapshot
      WHERE customer_id = ?
      ORDER BY snapshot_ts DESC
    )
    SELECT * FROM last_snap;
    """
    row = sqlc.fetch_one(sql, params=[event_ts, customer_id]) or {}

    rate_diff = None
    if row.get("current_rate") is not None and row.get("prev_rate") is not None:
        rate_diff = float(row["current_rate"]) - float(row["prev_rate"])

    return {
        "customer_id": customer_id,
        "current_rate": row.get("current_rate"),
        "prev_rate": row.get("prev_rate"),
        "rate_diff": rate_diff,
        "term_months": row.get("term_months"),
        "account_age_days": row.get("account_age_days"),
    }