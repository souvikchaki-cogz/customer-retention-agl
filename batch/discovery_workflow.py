"""Workflow-2 (Discovery): Batch n-gram mining for churn triggers with BH-FDR validation."""
import json
import math
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import precision_score
from shared.sql_client import SqlClient
from shared.pii import scrub_text


def load_snapshots():
    s = SqlClient()
    with s._conn() as cn:
        notes = pd.read_sql("SELECT customer_id, note_id, note_text, created_ts FROM notes_snapshot", cn)
        closures = pd.read_sql("SELECT customer_id, closure_ts FROM closures", cn)
        customers = pd.read_sql("SELECT customer_id FROM customers", cn)
    return notes, closures, customers


def label_notes_with_horizon(notes, closures, horizon_days=30):
    closures = closures.copy()
    closures["closure_ts"] = pd.to_datetime(closures["closure_ts"])
    notes["created_ts"] = pd.to_datetime(notes["created_ts"])
    notes = notes.merge(closures, on="customer_id", how="left")
    notes["label"] = (notes["closure_ts"] - notes["created_ts"]).dt.days.between(0, horizon_days)
    notes["label"] = notes["label"].fillna(False).astype(int)
    notes["text_clean"] = notes["note_text"].fillna("").map(scrub_text)
    return notes[["customer_id", "note_id", "text_clean", "created_ts", "label"]]


def mine_candidates(train, min_support=50, max_features=5000, ngram=(1, 3)):
    vect = CountVectorizer(lowercase=True, ngram_range=ngram, max_features=max_features, min_df=2)
    X = vect.fit_transform(train["text_clean"])
    y = train["label"].values
    vocab = np.array(vect.get_feature_names_out())

    counts_pos = X[y == 1].sum(axis=0).A1 + 0.5
    counts_neg = X[y == 0].sum(axis=0).A1 + 0.5
    support = counts_pos + counts_neg
    mask = support >= min_support
    vocab, counts_pos, counts_neg = vocab[mask], counts_pos[mask], counts_neg[mask]

    odds_ratio = (counts_pos / (counts_pos.sum() - counts_pos)) / (counts_neg / (counts_neg.sum() - counts_neg))
    lift = (counts_pos / counts_pos.sum()) / (counts_neg / counts_neg.sum())
    se = np.sqrt(1 / counts_pos + 1 / (counts_pos.sum() - counts_pos) + 1 / counts_neg + 1 / (counts_neg.sum() - counts_neg))
    z = np.log(odds_ratio) / se
    pvals = 2 * (1 - 0.5 * (1 + pd.Series(z).apply(lambda v: math.erf(abs(v) / math.sqrt(2)))))

    order = np.argsort(pvals)
    m = len(pvals)
    q = np.empty_like(pvals)
    prev = 1.0
    for i, idx in enumerate(order[::-1], start=1):
        rank = m - i + 1
        q[idx] = min(prev, pvals[idx] * m / rank)
        prev = q[idx]

    return pd.DataFrame({
        "phrase": vocab, "support": support[mask], "lift": lift,
        "odds_ratio": odds_ratio, "p_value": pvals, "fdr": q,
    }).sort_values("fdr")


def validate_on_test(cands, test, top_k=100):
    import re
    phrases = cands.head(top_k)["phrase"].tolist()
    pattern = "|".join([re.escape(p) for p in phrases])
    preds = test["text_clean"].str.contains(pattern, case=False, regex=True)
    prec = precision_score(test["label"], preds.astype(int), zero_division=0)
    counts = test["text_clean"].str.count(pattern)
    topk_idx = counts.nlargest(top_k).index
    p_at_k = test.loc[topk_idx, "label"].mean() if len(topk_idx) else 0.0
    return float(prec), float(p_at_k)


def write_discovery_cards(cands, examples):
    sql_client = SqlClient()
    for _, row in cands.head(200).iterrows():
        ex_rows = examples[examples["text_clean"].str.contains(row["phrase"], case=False)].head(3)
        ex = [e[:240] for e in ex_rows["text_clean"].tolist()]
        sql_client.fetch_one(
            "INSERT INTO discovery_cards (phrase,support,lift,odds_ratio,fdr,examples_json,status,created_ts) "
            "VALUES (?,?,?,?,?,?,'CANDIDATE',SYSDATETIME())",
            params=[row["phrase"], int(row["support"]), float(row["lift"]),
                    float(row["odds_ratio"]), float(row["fdr"]), json.dumps(ex)],
        )


def main():
    notes, closures, customers = load_snapshots()
    labeled = label_notes_with_horizon(notes, closures, horizon_days=30)
    cust_train, cust_test = train_test_split(labeled["customer_id"].unique(), test_size=0.3, random_state=42)
    train = labeled[labeled["customer_id"].isin(cust_train)]
    test = labeled[labeled["customer_id"].isin(cust_test)]

    cands = mine_candidates(train, min_support=30, max_features=8000, ngram=(1, 3))
    prec, p_at_k = validate_on_test(cands[cands["fdr"] <= 0.1], test, top_k=100)
    print(f"Discovery validation: Precision={prec:.3f}, P@100={p_at_k:.3f}")
    write_discovery_cards(cands[cands["fdr"] <= 0.1], test)


if __name__ == "__main__":
    main()