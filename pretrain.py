"""
Guardian-Sleuth: Pre-Training Script
======================================
Run ONCE before demo to:
  1. Load PaySim + NCUA data into DuckDB
  2. Build 24h-window cliques via C++ Bron-Kerbosch
  3. Train FLHR-MCL (Transformer+BiLSTM + GCN + HGNN + HGBT classifier)
  4. Score every account in the loaded dataset
  5. Save model artifacts to data/artifacts/ for instant app startup

Usage:
    python3 pretrain.py

Takes ~3-8 minutes depending on machine. Run once; the app then loads in <5s.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from core.data_manager import DataManager, PAYSIM_PATH, _STAT_FEATURE_NAMES
from core.models import AMLPipeline, generate_flags

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ARTIFACT_DIR  = "data/artifacts"
PAYSIM_CSV    = PAYSIM_PATH          # data/paysim.csv
MAX_ROWS      = 150_000              # rows from PaySim for clique + feature building
TRAIN_ACCTS   = 3_000               # accounts fed to GCN/HGNN (memory constraint)
SCORE_ACCTS   = 10_000              # accounts to score and write to DuckDB
EPOCHS        = 30                  # contrastive pre-training epochs (fast for demo)
WINDOW_HOURS  = 24


def load_paysim_stratified(csv_path: str, max_rows: int) -> pd.DataFrame:
    """
    Load PaySim keeping ALL fraud rows + a random sample of non-fraud
    so the classifier sees enough positive examples.
    """
    log.info("Reading PaySim CSV (this may take ~30s for the full 6M-row file)…")
    df = pd.read_csv(csv_path)

    fraud  = df[df["isFraud"] == 1]
    normal = df[df["isFraud"] == 0].sample(
        n=min(max_rows - len(fraud), max_rows),
        random_state=42,
    )
    out = pd.concat([fraud, normal], ignore_index=True).sample(frac=1, random_state=42)
    log.info("Loaded %d rows (%d fraud, %d normal)", len(out), len(fraud), len(normal))
    return out


def build_cliques(dm: DataManager, tx_df: pd.DataFrame) -> dict[str, list[list[str]]]:
    """
    Build fraud-ring hyperedges per 24h window using two strategies:

    Strategy A — Bron-Kerbosch maximal cliques (used when graph is dense):
        Runs C++ engine on the undirected transaction subgraph per window.

    Strategy B — Shared-destination grouping (AML smurfing pattern):
        Groups source accounts that funneled money to the same destination
        within the window. This captures the "multiple accounts → single
        cashout merchant" pattern common in PaySim fraud rings.

    Both sets of hyperedges are merged. Strategy B is the primary one for
    PaySim since its graph is star-shaped (few natural triangles).
    """
    try:
        import clique_engine as ce
        use_cpp = True
        log.info("Using C++ Bron-Kerbosch engine")
    except ImportError:
        use_cpp = False
        log.warning("C++ engine not found — using Python fallback (slower)")

    tx_df = tx_df.copy()
    tx_df["timestamp"] = pd.to_datetime(tx_df["timestamp"])
    tx_df["window"] = (
        (tx_df["timestamp"] - tx_df["timestamp"].min())
        .dt.total_seconds() // (WINDOW_HOURS * 3600)
    ).astype(int)

    cliques_by_account: dict[str, list[list[str]]] = {}
    total_cliques = 0
    windows = tx_df["window"].nunique()
    log.info("Processing %d time windows…", windows)

    for win_id, win_df in tx_df.groupby("window"):
        # --- Strategy A: Bron-Kerbosch on undirected subgraph ---
        nodes = list(set(win_df["account_from"].tolist() + win_df["account_to"].tolist()))
        if len(nodes) >= 3:
            idx   = {n: i for i, n in enumerate(nodes)}
            edges = list({
                (min(idx[r["account_from"]], idx[r["account_to"]]),
                 max(idx[r["account_from"]], idx[r["account_to"]]))
                for _, r in win_df.iterrows()
                if r["account_from"] in idx and r["account_to"] in idx
            })
            if edges:
                raw = ce.find_cliques_windowed(len(nodes), edges, min_size=2) if use_cpp \
                      else _py_bk(len(nodes), edges)
                rev = {i: n for n, i in idx.items()}
                for clique in raw:
                    named = [rev[i] for i in clique if i in rev]
                    if len(named) >= 2:
                        for acct in named:
                            cliques_by_account.setdefault(acct, [])
                            cliques_by_account[acct].append(named)
                        total_cliques += 1

        # --- Strategy B: shared-destination grouping (smurfing pattern) ---
        # Group C-accounts (not merchants) by destination within this window
        c_txs = win_df[win_df["account_from"].str.startswith("C")]
        for dest, grp in c_txs.groupby("account_to"):
            sources = list(grp["account_from"].unique())
            if len(sources) >= 2:  # ≥2 senders → same destination = ring
                ring = sources + [dest]
                for acct in ring:
                    cliques_by_account.setdefault(acct, [])
                    cliques_by_account[acct].append(ring)
                total_cliques += 1

    log.info("Found %d hyperedges across %d accounts", total_cliques, len(cliques_by_account))
    return cliques_by_account


def _py_bk(n: int, edges: list) -> list[list[int]]:
    adj: list[set] = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v); adj[v].add(u)
    results: list[list[int]] = []

    def bk(R, P, X):
        if not P and not X:
            if len(R) >= 3:
                results.append(sorted(R))
            return
        pivot = max(P + X, key=lambda u: len(adj[u] & set(P)))
        for v in [u for u in P if u not in adj[pivot]]:
            bk(R + [v], [u for u in P if u in adj[v]], [u for u in X if u in adj[v]])
            P.remove(v); X.append(v)

    bk([], list(range(n)), [])
    return results


def main() -> None:
    t0 = time.time()
    os.makedirs("data/artifacts", exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    log.info("=== Step 1/5: Loading data ===")
    dm = DataManager()

    raw_df = load_paysim_stratified(PAYSIM_CSV, MAX_ROWS)

    # Rename PaySim columns to schema
    raw_df = raw_df.rename(columns={
        "type": "tx_type",
        "nameOrig": "account_from",
        "nameDest": "account_to",
        "isFraud": "is_fraud",
    })
    from core.data_manager import _steps_to_timestamps
    raw_df["timestamp"] = _steps_to_timestamps(raw_df["step"])
    raw_df["tx_id"] = [f"TX{i:08d}" for i in range(len(raw_df))]
    raw_df["is_fraud"] = raw_df["is_fraud"].astype(bool)

    keep = ["tx_id", "account_from", "account_to", "timestamp", "amount", "tx_type", "is_fraud"]
    tx_df = raw_df[[c for c in keep if c in raw_df.columns]].copy()

    dm.con.execute("DELETE FROM transactions")
    dm.con.execute("INSERT INTO transactions SELECT * FROM tx_df")
    count = dm.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    log.info("Loaded %d transactions into DuckDB", count)

    dm.load_macro()
    log.info("NCUA macro data loaded")

    # ------------------------------------------------------------------
    # 2. Build cliques
    # ------------------------------------------------------------------
    log.info("=== Step 2/5: Building fraud-ring cliques ===")
    cliques_by_account = build_cliques(dm, tx_df)
    all_cliques = list({
        tuple(sorted(c))
        for clqs in cliques_by_account.values()
        for c in clqs
    })
    all_cliques = [list(c) for c in all_cliques]

    # Persist cliques to DuckDB
    dm.con.execute("DELETE FROM cliques")
    ts_min = tx_df["timestamp"].min()
    ts_max = tx_df["timestamp"].max()
    if all_cliques:
        rows = [(f"W{i}", ts_min, ts_max, json.dumps(c), len(c)) for i, c in enumerate(all_cliques)]
        dm.con.executemany("INSERT INTO cliques VALUES (?, ?, ?, ?, ?)", rows)
    log.info("Persisted %d cliques to DuckDB", len(all_cliques))

    # ------------------------------------------------------------------
    # 3. Build feature matrices for training accounts
    # ------------------------------------------------------------------
    log.info("=== Step 3/5: Building features ===")

    # Prioritise: fraud accounts + clique members + random sample
    fraud_accounts = list(tx_df[tx_df["is_fraud"]]["account_from"].unique())
    clique_accounts = list(cliques_by_account.keys())
    all_accounts = list(set(tx_df["account_from"].tolist() + tx_df["account_to"].tolist()))

    # Build training set: fraud + clique + random sample, capped
    priority = list(dict.fromkeys(fraud_accounts + clique_accounts))
    remaining = [a for a in all_accounts if a not in set(priority)]
    np.random.seed(42)
    np.random.shuffle(remaining)
    train_accounts = (priority + remaining)[:TRAIN_ACCTS]
    log.info("Training on %d accounts (%d fraud, %d in cliques)",
             len(train_accounts), len(fraud_accounts), len(clique_accounts))

    stat_rows, temp_rows, tx_counts, labels = [], [], [], []
    for i, aid in enumerate(train_accounts):
        if i % 500 == 0:
            log.info("  Building features %d/%d…", i, len(train_accounts))
        bundle = dm.build_node_features(aid)
        stat_vec = np.array(
            [bundle["stat_features"].get(f, 0.0) for f in _STAT_FEATURE_NAMES],
            dtype=np.float32,
        )
        stat_rows.append(stat_vec)
        temp_rows.append(bundle["temporal_seq"])
        tx_counts.append(bundle["tx_count"])
        is_fraud = tx_df[
            (tx_df["account_from"] == aid) | (tx_df["account_to"] == aid)
        ]["is_fraud"].any()
        labels.append(int(is_fraud))

    stat_matrix   = np.vstack(stat_rows)
    temporal_seqs = np.stack(temp_rows, axis=0)
    tx_count_arr  = np.array(tx_counts, dtype=np.float32)
    labels_arr    = np.array(labels, dtype=np.int32)

    acct_cliques = [cliques_by_account.get(a, []) for a in train_accounts]
    flat_cliques = [c for cs in acct_cliques for c in cs]
    log.info("Labels: %d fraud / %d normal", labels_arr.sum(), (labels_arr == 0).sum())

    # ------------------------------------------------------------------
    # 4. Train
    # ------------------------------------------------------------------
    log.info("=== Step 4/5: Training FLHR-MCL (%d epochs) ===", EPOCHS)
    pipeline = AMLPipeline(device="cpu", epochs=EPOCHS, hidden_dim=64, lr=0.1)
    metrics = pipeline.fit(
        account_ids=train_accounts,
        stat_matrix=stat_matrix,
        temporal_seqs=temporal_seqs,
        tx_counts=tx_count_arr,
        tx_df=tx_df,
        cliques=flat_cliques,
        labels=labels_arr,
    )
    log.info("Training complete. CV F1=%.4f  |  Test(20%%) Acc=%.4f  F1=%.4f  AUC=%.4f",
             metrics.get("train_cv_f1", metrics.get("avg_f1", 0)),
             metrics.get("test_accuracy", 0),
             metrics.get("test_f1", 0),
             metrics.get("test_auc", 0))

    # ------------------------------------------------------------------
    # 5. Score all accounts + persist
    # ------------------------------------------------------------------
    log.info("=== Step 5/5: Scoring accounts ===")

    # Score a broader set than just training accounts
    score_candidates = list(dict.fromkeys(fraud_accounts + clique_accounts + remaining))
    score_accounts = score_candidates[:SCORE_ACCTS]
    log.info("Scoring %d accounts…", len(score_accounts))

    # Build features for scoring accounts
    s_stat, s_temp, s_txc = [], [], []
    valid_score_accounts = []
    for aid in score_accounts:
        try:
            b = dm.build_node_features(aid)
            s_stat.append(np.array(
                [b["stat_features"].get(f, 0.0) for f in _STAT_FEATURE_NAMES],
                dtype=np.float32,
            ))
            s_temp.append(b["temporal_seq"])
            s_txc.append(b["tx_count"])
            valid_score_accounts.append(aid)
        except Exception:
            continue

    scores = pipeline.predict(
        account_ids=valid_score_accounts,
        stat_matrix=np.vstack(s_stat),
        temporal_seqs=np.stack(s_temp, axis=0),
        tx_counts=np.array(s_txc, dtype=np.float32),
        tx_df=tx_df,
        cliques=flat_cliques,
    )

    for aid, score in zip(valid_score_accounts, scores):
        monthly = dm.get_monthly_activity(aid)
        acct_clqs = cliques_by_account.get(aid, [])
        b = dm.build_node_features(aid)
        flags = generate_flags(aid, float(score), b["stat_features"], acct_clqs, monthly)
        dm.write_risk_score(aid, float(score), flags)

    n_scored = dm.con.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    n_high   = dm.con.execute("SELECT COUNT(*) FROM risk_scores WHERE risk_label='HIGH'").fetchone()[0]
    log.info("Scored %d accounts — %d HIGH RISK", n_scored, n_high)

    # Save model artifacts
    pipeline.save_artifacts(ARTIFACT_DIR)

    # Export a parquet snapshot so Streamlit can read risk scores without
    # needing a live DuckDB write connection (avoids lock conflicts).
    log.info("Exporting parquet snapshots for Streamlit…")
    dm.con.execute("""
        COPY risk_scores TO 'data/risk_scores.parquet' (FORMAT PARQUET)
    """)
    dm.con.execute("""
        COPY (SELECT window_id, window_start, window_end, clique_members, clique_size
              FROM cliques) TO 'data/cliques.parquet' (FORMAT PARQUET)
    """)
    dm.con.execute("""
        COPY transactions TO 'data/transactions.parquet' (FORMAT PARQUET)
    """)
    dm.con.execute("""
        COPY macro_data TO 'data/macro_data.parquet' (FORMAT PARQUET)
    """)
    log.info("Parquet snapshots written to data/")

    # Print some demo accounts for the pitch
    log.info("")
    log.info("=== DEMO ACCOUNTS FOR PITCH ===")
    log.info("HIGH RISK (fraud ring members):")
    high_rows = dm.con.execute("""
        SELECT account_id, risk_score FROM risk_scores
        WHERE risk_label = 'HIGH'
        ORDER BY risk_score DESC LIMIT 5
    """).fetchall()
    for aid, score in high_rows:
        log.info("  %s  →  %.3f", aid, score)

    log.info("LOW RISK (clean accounts):")
    low_rows = dm.con.execute("""
        SELECT account_id, risk_score FROM risk_scores
        WHERE risk_label = 'LOW'
        ORDER BY risk_score ASC LIMIT 3
    """).fetchall()
    for aid, score in low_rows:
        log.info("  %s  →  %.3f", aid, score)

    elapsed = time.time() - t0
    log.info("")
    log.info("Pre-training complete in %.1f minutes", elapsed / 60)
    log.info("Run:  streamlit run main.py")


if __name__ == "__main__":
    main()
