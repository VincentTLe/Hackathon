"""
Guardian-Sleuth: Main Entry Point
===================================
Run with:
    streamlit run main.py

Single-page layout:
  1. Header
  2. Dataset upload + train (collapses to status strip once trained)
  3. Account search bar
  4. 4-panel analyst dashboard (appears after search)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import io

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARTIFACT_DIR = str(Path(__file__).parent / "data" / "artifacts")


def _normalize_tx_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw uploaded CSV to the internal schema before training."""
    from core.data_manager import _steps_to_timestamps
    df = df.copy()
    df.columns = df.columns.str.strip()
    col_map = {
        "type": "tx_type", "transaction_type": "tx_type",
        "nameOrig": "account_from", "from_account": "account_from",
        "sender": "account_from", "from": "account_from",
        "nameDest": "account_to", "to_account": "account_to",
        "receiver": "account_to", "to": "account_to",
        "isFraud": "is_fraud", "fraud": "is_fraud", "label": "is_fraud",
        "date": "timestamp", "datetime": "timestamp", "time": "timestamp",
        "transaction_amount": "amount", "value": "amount",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    if "timestamp" not in df.columns:
        if "step" in df.columns:
            df["timestamp"] = _steps_to_timestamps(df["step"])
        else:
            df["timestamp"] = pd.Timestamp("2019-01-01")
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").fillna(
            pd.Timestamp("2019-01-01")
        )
    if "tx_id" not in df.columns:
        df["tx_id"] = [f"TX{i:08d}" for i in range(len(df))]
    if "tx_type" not in df.columns:
        df["tx_type"] = "TRANSFER"
    if "is_fraud" not in df.columns:
        df["is_fraud"] = False
    df["is_fraud"] = df["is_fraud"].astype(bool)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Guardian-Sleuth | AML Syndicate Sleuth",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }

    [data-testid="stSidebar"] { display: none; }
    [data-testid="collapsedControl"] { display: none; }

    .stTextInput > div > div > input {
        background-color: #1c1f26;
        color: #e0e0e0;
        border: 1px solid #30363d;
        border-radius: 6px;
        font-size: 1.1rem;
        padding: 10px 14px;
    }
    .stTextInput > div > div > input:focus { border-color: #4fc3f7; box-shadow: none; }
    .stTextInput > div > div > input::placeholder { color: #555c6a; }

    .stButton > button {
        background: linear-gradient(135deg, #4fc3f7, #0288d1);
        color: #fff;
        border: none;
        border-radius: 6px;
        padding: 10px 28px;
        font-weight: 700;
        font-size: 1rem;
        transition: opacity 0.2s;
    }
    .stButton > button:hover { opacity: 0.85; }

    [data-testid="stMetricValue"] { color: #4fc3f7; }
    hr { border-color: #2a2d35 !important; }
    .stCaption, caption { color: #8b949e !important; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* Hide Streamlit's native running spinner + stop button from top-right */
    [data-testid="stStatusWidget"] { display: none !important; }

    /* Demo button — distinct teal/green style */
    div[data-testid="stButton"].demo-btn > button {
        background: linear-gradient(135deg, #00c853, #00897b) !important;
        font-size: 0.95rem;
    }

    /* Training status box */
    .train-status {
        background: #12202f;
        border: 1px solid #1565c0;
        border-radius: 8px;
        padding: 12px 18px;
        margin: 8px 0;
        font-size: 0.95rem;
        color: #e0e0e0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
</style>
""", unsafe_allow_html=True)

BG_DARK     = "#0e1117"
BG_CARD     = "#1c1f26"
RED         = "#ff4b4b"
AMBER       = "#ffa500"
GREEN       = "#00c853"
BLUE_ACCENT = "#4fc3f7"
TEXT_LIGHT  = "#e0e0e0"


# ---------------------------------------------------------------------------
# Cached resource loader
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def load_resources():
    from core.data_manager import DataManager
    from core.models import AMLPipeline

    dm = DataManager(read_only=True)

    artifacts_exist = (
        Path(ARTIFACT_DIR).exists()
        and (Path(ARTIFACT_DIR) / "meta.json").exists()
        and (Path(ARTIFACT_DIR) / "hgbt.joblib").exists()
    )

    if artifacts_exist:
        pipeline = AMLPipeline.load_artifacts(ARTIFACT_DIR)
        trained  = True
    else:
        pipeline = None
        trained  = False

    return dm, pipeline, trained


dm, pipeline, model_trained = load_resources()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "active_account" not in st.session_state:
    st.session_state.active_account = None
if "demo_mode" not in st.session_state:
    st.session_state.demo_mode = False

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div style="text-align:center; padding: 36px 0 20px 0;">
        <h1 style="color:#4fc3f7; font-size:3rem; margin:0; letter-spacing:-1px;">
            🔍 Guardian-Sleuth
        </h1>
        <p style="color:#8b949e; font-size:1.1rem; margin-top:8px;">
            Anti-Money Laundering &nbsp;·&nbsp; Syndicate Detection &nbsp;·&nbsp;
            Macro-Economic Correlation
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<hr style='border-color:#2a2d35; margin: 0 0 24px 0;'>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 1: Dataset Upload & Training
# ---------------------------------------------------------------------------

def _count_transactions() -> int:
    try:
        return dm.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    except Exception:
        return 0


def _status(status_text, progress_bar, step: int, msg: str, pct: int, t0: float) -> None:
    """Render the cycling-indicator status line with time estimate."""
    progress_bar.progress(pct)
    elapsed = time.time() - t0
    if pct >= 10:
        estimated_total = elapsed / (pct / 100)
        remaining       = max(0, estimated_total - elapsed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        time_str = f"~{mins}m {secs}s remaining" if mins > 0 else f"~{secs}s remaining"
    else:
        time_str = "estimating time…"
    status_text.markdown(
        f"""<div class="train-status">
            🔄 &nbsp;<b>Step {step}/5</b> — {msg}
            &nbsp;&nbsp;&nbsp;⏱ <span style="color:#8b949e;">{time_str}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def _run_training_pipeline(tx_df: pd.DataFrame, progress_bar, status_text) -> dict:
    """Full inline training pipeline. Logs 80/20 test metrics to console only."""
    import json as _json
    from core.data_manager import DataManager, _STAT_FEATURE_NAMES
    from core.models import AMLPipeline, generate_flags

    # Normalise column names (PaySim uses nameOrig/nameDest/isFraud etc.)
    tx_df = _normalize_tx_df(tx_df)

    TRAIN_ACCTS  = 2_000
    SCORE_ACCTS  = 6_000
    EPOCHS       = 20
    WINDOW_HOURS = 24

    t0 = time.time()

    # Step 1 — Ingest
    _status(status_text, progress_bar, 1, "Ingesting dataset into DuckDB…", 3, t0)

    dm_w = DataManager()
    dm_w.ingest_uploaded_csv(tx_df)
    dm_w.load_macro()

    # Step 2 — Cliques
    _status(status_text, progress_bar, 2, "Detecting fraud-ring cliques…", 12, t0)

    try:
        import clique_engine as ce
        use_cpp = True
    except ImportError:
        use_cpp = False

    def _py_bk(n, edges):
        adj = [set() for _ in range(n)]
        for u, v in edges:
            adj[u].add(v); adj[v].add(u)
        results = []
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

    raw = tx_df.copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw["window"] = (
        (raw["timestamp"] - raw["timestamp"].min()).dt.total_seconds()
        // (WINDOW_HOURS * 3600)
    ).astype(int)

    cliques_by_account: dict = {}
    for _, win_df in raw.groupby("window"):
        nodes = list(set(win_df["account_from"].tolist() + win_df["account_to"].tolist()))
        if len(nodes) >= 3:
            idx = {n: i for i, n in enumerate(nodes)}
            # Vectorised edge building — replaces iterrows (100× faster)
            src = win_df["account_from"].map(idx)
            tgt = win_df["account_to"].map(idx)
            mask = src.notna() & tgt.notna()
            if mask.any():
                s = src[mask].astype(int).values
                t = tgt[mask].astype(int).values
                pairs = np.unique(
                    np.column_stack([np.minimum(s, t), np.maximum(s, t)]), axis=0
                )
                edges = [tuple(p) for p in pairs if p[0] != p[1]]
            else:
                edges = []
            if edges:
                rc = (ce.find_cliques_windowed(len(nodes), edges, min_size=2)
                      if use_cpp else _py_bk(len(nodes), edges))
                rev = {i: n for n, i in idx.items()}
                for clique in rc:
                    named = [rev[i] for i in clique if i in rev]
                    if len(named) >= 2:
                        for a in named:
                            cliques_by_account.setdefault(a, []).append(named)

        c_txs = win_df[win_df["account_from"].str.startswith("C", na=False)]
        for dest, grp in c_txs.groupby("account_to"):
            sources = list(grp["account_from"].unique())
            if 2 <= len(sources) <= 20:   # cap: popular merchants aren't fraud rings
                ring = sources + [dest]
                for a in ring:
                    cliques_by_account.setdefault(a, []).append(ring)

    all_cliques = [list(c) for c in {
        tuple(sorted(c)) for cs in cliques_by_account.values() for c in cs
    }]

    dm_w.con.execute("DELETE FROM cliques")
    if all_cliques:
        rows = [(f"W{i}", raw["timestamp"].min(), raw["timestamp"].max(),
                 _json.dumps(c), len(c)) for i, c in enumerate(all_cliques)]
        dm_w.con.executemany("INSERT INTO cliques VALUES (?, ?, ?, ?, ?)", rows)

    # Step 3 — Features
    _status(status_text, progress_bar, 3, "Building account feature matrices…", 40, t0)

    fraud_accounts  = list(raw[raw["is_fraud"]]["account_from"].unique()) if "is_fraud" in raw.columns else []
    clique_accounts = list(cliques_by_account.keys())
    all_accounts    = list(set(raw["account_from"].tolist() + raw["account_to"].tolist()))
    priority        = list(dict.fromkeys(fraud_accounts + clique_accounts))
    remaining       = [a for a in all_accounts if a not in set(priority)]
    np.random.seed(42); np.random.shuffle(remaining)
    train_accounts  = (priority + remaining)[:TRAIN_ACCTS]

    # Precompute fraud label set (avoids per-account DataFrame scan)
    fraud_set: set[str] = set()
    if "is_fraud" in raw.columns:
        fraud_mask = raw["is_fraud"]
        fraud_set  = set(raw.loc[fraud_mask, "account_from"].unique()) | \
                     set(raw.loc[fraud_mask, "account_to"].unique())

    # Single batch call replaces thousands of individual DuckDB queries
    bundles = dm_w.build_node_features_batch(train_accounts)

    stat_rows, temp_rows, tx_counts, labels = [], [], [], []
    for aid in train_accounts:
        b = bundles[aid]
        stat_rows.append(np.array(
            [b["stat_features"].get(f, 0.0) for f in _STAT_FEATURE_NAMES], dtype=np.float32
        ))
        temp_rows.append(b["temporal_seq"])
        tx_counts.append(b["tx_count"])
        labels.append(int(aid in fraud_set))

    stat_matrix   = np.vstack(stat_rows)
    temporal_seqs = np.stack(temp_rows, axis=0)
    tx_count_arr  = np.array(tx_counts, dtype=np.float32)
    labels_arr    = np.array(labels, dtype=np.int32)
    flat_cliques  = [c for cs in [cliques_by_account.get(a, []) for a in train_accounts] for c in cs]

    # Step 4 — Train
    _status(status_text, progress_bar, 4, f"Training FLHR-MCL ({EPOCHS} epochs)…", 58, t0)

    model_pipeline = AMLPipeline(device="cpu", epochs=EPOCHS, hidden_dim=64, lr=0.1)
    metrics = model_pipeline.fit(
        account_ids=train_accounts,
        stat_matrix=stat_matrix,
        temporal_seqs=temporal_seqs,
        tx_counts=tx_count_arr,
        tx_df=raw,
        cliques=flat_cliques,
        labels=labels_arr,
    )

    # Step 5 — Score
    _status(status_text, progress_bar, 5, "Scoring all accounts…", 78, t0)

    score_candidates = list(dict.fromkeys(fraud_accounts + clique_accounts + remaining))
    score_accts      = score_candidates[:SCORE_ACCTS]
    score_bundles    = dm_w.build_node_features_batch(score_accts)

    valid_accts = [a for a in score_accts if score_bundles[a]["tx_count"] > 0]
    s_stat = np.vstack([
        np.array([score_bundles[a]["stat_features"].get(f, 0.0) for f in _STAT_FEATURE_NAMES],
                 dtype=np.float32)
        for a in valid_accts
    ])
    s_temp = np.stack([score_bundles[a]["temporal_seq"] for a in valid_accts], axis=0)
    s_txc  = np.array([score_bundles[a]["tx_count"] for a in valid_accts], dtype=np.float32)

    scores = model_pipeline.predict(
        account_ids=valid_accts,
        stat_matrix=s_stat,
        temporal_seqs=s_temp,
        tx_counts=s_txc,
        tx_df=raw,
        cliques=flat_cliques,
    )

    # Write risk scores (get_monthly_activity still per-account, but only for scored set)
    stat_for_flags = dm_w.build_stat_features_batch(valid_accts)
    for aid, score in zip(valid_accts, scores):
        monthly = dm_w.get_monthly_activity(aid)
        flags   = generate_flags(
            aid, float(score),
            stat_for_flags.get(aid, {}),
            cliques_by_account.get(aid, []),
            monthly,
        )
        dm_w.write_risk_score(aid, float(score), flags)

    model_pipeline.save_artifacts(ARTIFACT_DIR)

    for table, fname in [
        ("risk_scores", "risk_scores"), ("cliques", "cliques"),
        ("transactions", "transactions"), ("macro_data", "macro_data"),
    ]:
        dm_w.con.execute(f"COPY {table} TO 'data/{fname}.parquet' (FORMAT PARQUET)")

    dm_w.close()
    progress_bar.progress(100)
    elapsed_total = time.time() - t0
    status_text.markdown(
        f"""<div class="train-status" style="border-color:#00c853;">
            ✅ &nbsp;<b>Complete</b> — model trained and scored in
            <b>{elapsed_total/60:.1f} min</b>. Check terminal for accuracy metrics.
        </div>""",
        unsafe_allow_html=True,
    )
    return metrics


n_tx = _count_transactions()
demo_ready = model_trained  # pretrained artifacts exist

# ---- Handle "Use Demo" click ----
if st.session_state.demo_mode and not demo_ready:
    st.session_state.demo_mode = False  # artifacts gone, reset
    st.warning("No pretrained model found. Please upload a CSV and click Analyze.", icon="⚠️")

if (n_tx > 0 and model_trained) or st.session_state.demo_mode:
    # ── Compact status strip ─────────────────────────────────────────────
    try:
        n_scored = dm.con.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
        n_high   = dm.con.execute("SELECT COUNT(*) FROM risk_scores WHERE risk_label='HIGH'").fetchone()[0]
    except Exception:
        n_scored = n_high = 0

    mode_badge = (
        "<span style='color:#00c853; font-weight:700;'>DEMO MODE</span> &nbsp;·&nbsp;"
        if st.session_state.demo_mode and n_tx == 0
        else ""
    )
    st.markdown(
        f"""
        <div style="background:#0d2137; border:1px solid #1565c0; border-radius:8px;
                    padding:10px 20px; color:#8b949e; font-size:0.83rem;
                    display:flex; align-items:center; gap:12px;">
            🟢 &nbsp; {mode_badge}
            <b style="color:{BLUE_ACCENT};">{n_tx:,}</b> transactions loaded &nbsp;·&nbsp;
            <b style="color:{BLUE_ACCENT};">{n_scored:,}</b> accounts scored &nbsp;·&nbsp;
            <b style="color:{RED};">{n_high:,}</b> flagged HIGH RISK &nbsp;·&nbsp;
            FLHR-MCL · Transformer + BiLSTM + GCN + HGNN
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("🔄  Replace dataset / retrain model"):
        uploaded = st.file_uploader(
            "Upload a new transaction CSV to replace the current dataset",
            type=["csv"],
            key="retrain_uploader",
        )
        if uploaded:
            raw_bytes_rt = uploaded.read()
            uploaded.seek(0)
            df_prev   = pd.read_csv(uploaded, nrows=5)
            n_rows_rt = sum(1 for _ in io.BytesIO(raw_bytes_rt)) - 1
            st.caption(f"{n_rows_rt:,} rows · {df_prev.shape[1]} columns")
            if st.button("Analyze", key="retrain_btn"):
                pb     = st.progress(0)
                st_txt = st.empty()
                try:
                    df_full = pd.read_csv(io.BytesIO(raw_bytes_rt))
                    _run_training_pipeline(df_full, pb, st_txt)
                    st.session_state.demo_mode = False
                    st.cache_resource.clear()
                    time.sleep(1.5)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Training failed: {exc}")

else:
    # ── Upload card ──────────────────────────────────────────────────────
    st.markdown(
        f"<h3 style='color:{BLUE_ACCENT}; margin-bottom:4px;'>Upload Transaction Dataset</h3>",
        unsafe_allow_html=True,
    )

    col_up, col_hint = st.columns([2, 1])

    with col_hint:
        st.markdown(
            f"""
            <div style="background:{BG_CARD}; border-radius:8px; padding:14px 16px; height:100%;">
                <div style="color:{BLUE_ACCENT}; font-weight:700; font-size:0.78rem;
                            text-transform:uppercase; letter-spacing:0.08em;">Accepted column names</div>
                <div style="color:{TEXT_LIGHT}; font-size:0.8rem; margin-top:8px; line-height:1.75;">
                    <b>Sender:</b> nameOrig, account_from, sender<br>
                    <b>Receiver:</b> nameDest, account_to, receiver<br>
                    <b>Amount:</b> amount, transaction_amount, value<br>
                    <b>Type:</b> type, tx_type, transaction_type<br>
                    <b>Fraud label:</b> isFraud, is_fraud, fraud, label<br>
                    <b>Timestamp:</b> timestamp, date, datetime<br>
                    <b>PaySim step:</b> step (auto-converted to datetime)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_up:
        # ── Use Demo shortcut ────────────────────────────────────────────
        if demo_ready:
            demo_col, _ = st.columns([1, 2])
            with demo_col:
                if st.button("🎯  Use Demo", use_container_width=True, key="demo_btn"):
                    st.session_state.demo_mode = True
                    st.rerun()
            st.markdown(
                "<div style='text-align:center; color:#555c6a; font-size:0.8rem;"
                " margin: 4px 0 10px 0;'>— or upload your own dataset below —</div>",
                unsafe_allow_html=True,
            )

        # ── File uploader ────────────────────────────────────────────────
        uploaded = st.file_uploader(
            "Drop your transaction CSV here (up to 10 GB)",
            type=["csv"],
            key="initial_uploader",
        )

        if uploaded is not None:
            try:
                df_preview = pd.read_csv(uploaded, nrows=5)
                uploaded.seek(0)
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")
                df_preview = None

            if df_preview is not None:
                raw_bytes = uploaded.read()
                uploaded.seek(0)
                n_rows = sum(1 for _ in io.BytesIO(raw_bytes)) - 1
                st.success(f"Loaded **{n_rows:,} rows** × **{df_preview.shape[1]} columns**", icon="✅")

                fraud_col = next(
                    (c for c in df_preview.columns
                     if c.lower() in ("isfraud", "is_fraud", "fraud", "label")), None
                )
                if not fraud_col:
                    st.warning(
                        "No fraud label column detected — add an `isFraud` column for "
                        "supervised training. Model will still run in unsupervised mode.",
                        icon="⚠️",
                    )

                with st.expander("Preview (first 5 rows)"):
                    st.dataframe(df_preview, use_container_width=True)

                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("⚡  Analyze", use_container_width=True, key="train_btn"):
                    pb     = st.progress(0)
                    st_txt = st.empty()
                    try:
                        df_full = pd.read_csv(io.BytesIO(raw_bytes))
                        _run_training_pipeline(df_full, pb, st_txt)
                        st.cache_resource.clear()
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Training failed: {exc}", icon="🚫")
                        logger.exception("Training error")

st.markdown("<hr style='border-color:#2a2d35; margin: 24px 0;'>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 2: Account Search
# ---------------------------------------------------------------------------

if not model_trained:
    st.markdown(
        f"""
        <div style="text-align:center; padding:20px; color:#555c6a; font-size:0.95rem;">
            ⬆️ Upload a dataset and train the model to enable account search.
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    if st.session_state.active_account:
        if st.button("← New Search"):
            st.session_state.active_account = None
            st.rerun()

        from views import analyst_dashboard
        analyst_dashboard.render(
            account_id=st.session_state.active_account,
            dm=dm,
            pipeline=pipeline,
        )

    else:
        st.markdown(
            f"<h3 style='color:{BLUE_ACCENT}; margin-bottom:8px;'>Investigate Account</h3>",
            unsafe_allow_html=True,
        )

        _, col_search, _ = st.columns([1, 2, 1])
        with col_search:
            account_input = st.text_input(
                "",
                placeholder="Enter Account ID to initiate risk assessment…",
                label_visibility="collapsed",
                key="search_input",
            )
            if st.button("🔎  Analyse Account", use_container_width=True):
                if account_input.strip():
                    aid = account_input.strip()
                    if not dm.account_exists(aid):
                        st.error(f"Account **{aid}** not found in the transaction database.", icon="🚫")
                    else:
                        st.session_state.active_account = aid
                        st.rerun()
                else:
                    st.warning("Please enter an Account ID.", icon="⚠️")

        # Feature highlight cards
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        for col, (icon, title, desc) in zip(
            [c1, c2, c3, c4],
            [
                ("⚡", "Instant Risk Score",  "LightGBM-class risk rating 0–100"),
                ("🕸️", "Syndicate Graph",      "Interactive 2-hop ego network with clique detection"),
                ("📈", "Macro Overlay",        "NCUA CC rate vs. fraud activity timeline"),
                ("🚨", "Red Flag Engine",      "Plain-English behavioural indicators, severity-ranked"),
            ],
        ):
            with col:
                st.markdown(
                    f"""
                    <div style="background:{BG_CARD}; border-radius:10px; padding:18px 14px;
                                text-align:center; height:120px;">
                        <div style="font-size:1.8rem;">{icon}</div>
                        <div style="color:{BLUE_ACCENT}; font-weight:700; font-size:0.85rem;
                                    margin:6px 0 4px 0;">{title}</div>
                        <div style="color:#8b949e; font-size:0.75rem;">{desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
