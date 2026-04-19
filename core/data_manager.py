"""
Guardian-Sleuth: Data Manager
==============================
Owns all data I/O:
  - DuckDB schema creation and queries
  - PaySim CSV ingestion
  - NCUA credit card rate data (live scrape or local CSV fallback)
  - Macro-micro temporal fusion via Pandas merge_asof
  - Per-account statistical and temporal feature building
  - Risk score persistence and lookup

NCUA source: https://ncua.gov/analysis/cuso-economic-data/credit-union-bank-rates
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.parent
DB_PATH = str(_HERE / "data" / "guardian.duckdb")
PAYSIM_PATH = str(_HERE / "data" / "paysim.csv")
NCUA_CSV_PATH = str(_HERE / "data" / "ncua_rates.csv")
RATE_GAPS_PATH = str(_HERE / "data" / "rate_gaps_2008_2025.csv")

# ---------------------------------------------------------------------------
# NCUA fetch helpers
# ---------------------------------------------------------------------------

# NCUA publishes rate data at this JSON endpoint (rates page uses this API)
_NCUA_API = (
    "https://www.ncua.gov/analysis/cuso-economic-data/credit-union-bank-rates"
)
# Fallback: static mock if the network is unavailable during hackathon
_NCUA_MOCK = [
    ("2019-01-01", 16.88),
    ("2019-04-01", 17.14),
    ("2019-07-01", 17.14),
    ("2019-10-01", 16.97),
    ("2020-01-01", 16.61),
    ("2020-04-01", 15.78),
    ("2020-07-01", 15.09),
    ("2020-10-01", 14.65),
    ("2021-01-01", 14.75),
    ("2021-04-01", 14.61),
    ("2021-07-01", 14.61),
    ("2021-10-01", 14.51),
    ("2022-01-01", 14.56),
    ("2022-04-01", 15.13),
    ("2022-07-01", 16.27),
    ("2022-10-01", 18.43),
    ("2023-01-01", 20.09),
    ("2023-04-01", 20.77),
    ("2023-07-01", 21.19),
    ("2023-10-01", 21.47),
    ("2024-01-01", 21.59),
    ("2024-04-01", 21.51),
]


def _load_rate_gaps_csv(path: str) -> pd.DataFrame:
    """
    Parse the NCUA rate_gaps CSV (columns: quarter, product, cu_rate, bank_rate, gap).
    Filters to Credit Card product only and maps quarter strings like '2008-March'
    to proper datetime objects.
    """
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()
    cc = df[df["product"].str.strip().str.lower() == "credit card"].copy()

    def _parse_quarter(q: str) -> pd.Timestamp:
        parts = str(q).strip().split("-", 1)
        if len(parts) == 2:
            try:
                return pd.to_datetime(f"{parts[0]}-{parts[1]}-01", format="%Y-%B-%d")
            except Exception:
                pass
        return pd.NaT

    cc["period_date"] = cc["quarter"].apply(_parse_quarter)
    cc = cc.dropna(subset=["period_date"])
    cc["ncua_cc_rate"] = pd.to_numeric(cc["cu_rate"], errors="coerce")
    cc = cc[["period_date", "ncua_cc_rate"]].dropna().sort_values("period_date")
    cc["rate_mom_delta"] = cc["ncua_cc_rate"].diff().fillna(0)
    return cc.reset_index(drop=True)


def _load_ncua_from_csv(path: str) -> pd.DataFrame:
    """Load NCUA rates from a locally saved CSV."""
    df = pd.read_csv(path)
    # Normalise column names — common variants from the NCUA download
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    rename = {}
    for col in df.columns:
        if "date" in col or "period" in col or "quarter" in col:
            rename[col] = "period_date"
        if "rate" in col or "interest" in col or "credit" in col:
            rename[col] = "ncua_cc_rate"
    df.rename(columns=rename, inplace=True)
    df["period_date"] = pd.to_datetime(df["period_date"])
    df["ncua_cc_rate"] = pd.to_numeric(df["ncua_cc_rate"], errors="coerce")
    df = df[["period_date", "ncua_cc_rate"]].dropna().sort_values("period_date")
    df["rate_mom_delta"] = df["ncua_cc_rate"].diff().fillna(0)
    return df.reset_index(drop=True)


def _load_ncua_mock() -> pd.DataFrame:
    """Return the hard-coded quarterly NCUA series as a DataFrame."""
    df = pd.DataFrame(_NCUA_MOCK, columns=["period_date", "ncua_cc_rate"])
    df["period_date"] = pd.to_datetime(df["period_date"])
    df.sort_values("period_date", inplace=True)
    df["rate_mom_delta"] = df["ncua_cc_rate"].diff().fillna(0)
    return df.reset_index(drop=True)


def fetch_ncua_rates(csv_path: str = NCUA_CSV_PATH) -> pd.DataFrame:
    """
    Load NCUA average credit card interest rates.

    Priority:
      1. rate_gaps_2008_2025.csv (richer 2008-2025 historical data)
      2. Local CSV at csv_path (downloaded from ncua.gov)
      3. Hard-coded quarterly mock (always available)

    Returns a DataFrame with columns:
        period_date       datetime64
        ncua_cc_rate      float   (% APR)
        rate_mom_delta    float   (change from prior period)
    """
    if os.path.exists(RATE_GAPS_PATH):
        try:
            logger.info("Loading NCUA rates from rate_gaps CSV: %s", RATE_GAPS_PATH)
            return _load_rate_gaps_csv(RATE_GAPS_PATH)
        except Exception as exc:
            logger.warning("rate_gaps load failed (%s); trying ncua_rates.csv", exc)
    if os.path.exists(csv_path):
        try:
            logger.info("Loading NCUA rates from local CSV: %s", csv_path)
            return _load_ncua_from_csv(csv_path)
        except Exception as exc:
            logger.warning("CSV load failed (%s); falling back to mock.", exc)
    logger.info("Using built-in NCUA mock data (quarterly 2019-2024)")
    return _load_ncua_mock()


# ---------------------------------------------------------------------------
# Timestamp helpers for PaySim
# ---------------------------------------------------------------------------

_PAYSIM_ORIGIN = pd.Timestamp("2019-01-01")


def _steps_to_timestamps(steps: pd.Series) -> pd.Series:
    """Convert PaySim integer steps (1 step = 1 hour) to real timestamps."""
    return _PAYSIM_ORIGIN + pd.to_timedelta(steps.astype(int) - 1, unit="h")


# ---------------------------------------------------------------------------
# DataManager
# ---------------------------------------------------------------------------


class DataManager:
    """
    Central data hub for Guardian-Sleuth.

    Usage
    -----
    dm = DataManager()
    dm.ingest_paysim("data/paysim.csv")
    dm.load_macro()
    features = dm.build_node_features("C1234567890")
    """

    def __init__(self, db_path: str = DB_PATH, read_only: bool = False):
        os.makedirs(Path(db_path).parent, exist_ok=True)
        self._macro_df: pd.DataFrame | None = None
        self._parquet_dir = Path(db_path).parent

        # Try read_only first; if the DB is locked by pretrain.py fall back to
        # an in-memory connection that loads from the parquet snapshots.
        try:
            self.con = duckdb.connect(db_path, read_only=read_only)
            if not read_only:
                self._create_schema()
        except Exception:
            import warnings
            warnings.warn(
                "DuckDB file is locked (pretrain.py still running?). "
                "Falling back to in-memory connection from parquet snapshots.",
                RuntimeWarning,
                stacklevel=2,
            )
            self.con = duckdb.connect(":memory:")
            self._load_from_parquet()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id        VARCHAR,
                account_from VARCHAR,
                account_to   VARCHAR,
                timestamp    TIMESTAMP,
                amount       DOUBLE,
                tx_type      VARCHAR,
                is_fraud     BOOLEAN
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS macro_data (
                period_date               DATE PRIMARY KEY,
                ncua_cc_rate             DOUBLE,
                rate_mom_delta           DOUBLE
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS cliques (
                window_id         VARCHAR,
                window_start      TIMESTAMP,
                window_end        TIMESTAMP,
                clique_members    JSON,
                clique_size       INTEGER
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS risk_scores (
                account_id    VARCHAR PRIMARY KEY,
                risk_score    DOUBLE,
                risk_label    VARCHAR,
                flags_json    JSON,
                analyzed_at   TIMESTAMP
            )
        """)

    # ------------------------------------------------------------------
    # Parquet fallback (used when DuckDB file is locked)
    # ------------------------------------------------------------------

    def _load_from_parquet(self) -> None:
        """Load all tables from parquet snapshots into the in-memory DuckDB."""
        self._create_schema()
        tables = {
            "transactions":  "transactions.parquet",
            "risk_scores":   "risk_scores.parquet",
            "cliques":       "cliques.parquet",
            "macro_data":    "macro_data.parquet",
        }
        for table, fname in tables.items():
            pq_path = self._parquet_dir / fname
            if pq_path.exists():
                self.con.execute(f"""
                    INSERT INTO {table} SELECT * FROM read_parquet('{pq_path}')
                """)
                n = self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                logger.info("Loaded %d rows into %s from parquet", n, table)
            else:
                logger.warning("Parquet snapshot not found: %s (run pretrain.py first)", pq_path)

    # ------------------------------------------------------------------
    # PaySim ingestion
    # ------------------------------------------------------------------

    def ingest_paysim(self, csv_path: str = PAYSIM_PATH, limit: int | None = None) -> int:
        """
        Load PaySim CSV into the transactions table.

        Parameters
        ----------
        csv_path : path to the PaySim CSV
        limit    : if set, only load the first N rows (useful for dev)

        Returns the number of rows inserted.
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(
                f"PaySim CSV not found at '{csv_path}'. "
                "Download from https://www.kaggle.com/datasets/ealaxi/paysim1"
            )

        logger.info("Loading PaySim from %s (limit=%s)", csv_path, limit)
        df = pd.read_csv(csv_path, nrows=limit)

        # Normalise column names (PaySim has camelCase)
        df.columns = df.columns.str.strip()
        rename_map = {
            "step": "step",
            "type": "tx_type",
            "amount": "amount",
            "nameOrig": "account_from",
            "nameDest": "account_to",
            "isFraud": "is_fraud",
        }
        df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)

        df["timestamp"] = _steps_to_timestamps(df["step"])
        df["tx_id"] = [f"TX{i:08d}" for i in range(len(df))]
        df["is_fraud"] = df["is_fraud"].astype(bool)

        keep = ["tx_id", "account_from", "account_to", "timestamp", "amount", "tx_type", "is_fraud"]
        df = df[[c for c in keep if c in df.columns]]

        # Wipe and reload (idempotent for hackathon)
        self.con.execute("DELETE FROM transactions")
        self.con.execute("INSERT INTO transactions SELECT * FROM df")

        count = self.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        logger.info("Loaded %d transactions into DuckDB", count)
        return count

    # ------------------------------------------------------------------
    # Uploaded dataset ingestion
    # ------------------------------------------------------------------

    def ingest_uploaded_csv(self, df: pd.DataFrame) -> int:
        """
        Ingest an analyst-uploaded DataFrame into the transactions table.
        Auto-maps common column name variants (PaySim, generic banking CSV).
        Returns the number of rows inserted.
        """
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
        if "amount" not in df.columns:
            raise ValueError(
                "Dataset must contain an 'amount' (or 'transaction_amount' / 'value') column."
            )
        if "account_from" not in df.columns or "account_to" not in df.columns:
            raise ValueError(
                "Dataset must contain sender/receiver account columns "
                "(e.g. 'nameOrig'/'nameDest', 'account_from'/'account_to', 'sender'/'receiver')."
            )

        df["is_fraud"] = df["is_fraud"].astype(bool)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

        keep = ["tx_id", "account_from", "account_to", "timestamp", "amount", "tx_type", "is_fraud"]
        df = df[[c for c in keep if c in df.columns]]

        self.con.execute("DELETE FROM transactions")
        self.con.execute("INSERT INTO transactions SELECT * FROM df")
        count = self.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        logger.info("Ingested %d rows from uploaded CSV", count)
        return count

    # ------------------------------------------------------------------
    # NCUA macro loading
    # ------------------------------------------------------------------

    def load_macro(self, csv_path: str = NCUA_CSV_PATH) -> None:
        """Load NCUA rates into memory and persist to DuckDB."""
        df = fetch_ncua_rates(csv_path)
        self._macro_df = df

        self.con.execute("DELETE FROM macro_data")
        self.con.execute("""
            INSERT INTO macro_data
            SELECT
                period_date::DATE,
                ncua_cc_rate,
                rate_mom_delta
            FROM df
        """)
        logger.info("Loaded %d NCUA macro rows", len(df))

    def get_macro_df(self) -> pd.DataFrame:
        if self._macro_df is None:
            self.load_macro()
        return self._macro_df  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Macro-micro temporal fusion
    # ------------------------------------------------------------------

    def interpolate_macro(
        self,
        tx_df: pd.DataFrame,
        macro_df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """
        Align NCUA monthly/quarterly rates to individual transaction timestamps.

        Uses merge_asof (backward fill) so each transaction row gets the most
        recent known NCUA rate at its timestamp.

        Returns tx_df with additional columns:
            ncua_cc_rate    float
            rate_mom_delta  float
        """
        if macro_df is None:
            macro_df = self.get_macro_df()

        tx_sorted = tx_df.sort_values("timestamp").copy()
        tx_sorted["timestamp"] = tx_sorted["timestamp"].astype("datetime64[us]")
        macro_sorted = macro_df.sort_values("period_date").copy()
        macro_sorted["timestamp_key"] = pd.to_datetime(macro_sorted["period_date"]).astype("datetime64[us]")

        fused = pd.merge_asof(
            tx_sorted,
            macro_sorted[["timestamp_key", "ncua_cc_rate", "rate_mom_delta"]],
            left_on="timestamp",
            right_on="timestamp_key",
            direction="backward",
        )
        fused["ncua_cc_rate"] = fused["ncua_cc_rate"].ffill().fillna(0)
        fused["rate_mom_delta"] = fused["rate_mom_delta"].fillna(0)
        fused.drop(columns=["timestamp_key"], errors="ignore", inplace=True)
        return fused

    # ------------------------------------------------------------------
    # Statistical feature extraction (23 features per account)
    # ------------------------------------------------------------------

    def _get_account_txs(self, account_id: str) -> pd.DataFrame:
        df = self.con.execute("""
            SELECT * FROM transactions
            WHERE account_from = ? OR account_to = ?
            ORDER BY timestamp
        """, [account_id, account_id]).df()
        return df

    def build_statistical_features(self, account_id: str) -> dict[str, float]:
        """
        Compute 23 statistical features for a given account.
        Based on features described in Section 3.2.1 of the FLHR-MCL paper.
        """
        df = self._get_account_txs(account_id)
        if df.empty:
            return {f: 0.0 for f in _STAT_FEATURE_NAMES}

        sent = df[df["account_from"] == account_id]
        recv = df[df["account_to"] == account_id]
        amounts = df["amount"]

        feats: dict[str, float] = {
            "tx_count":          float(len(df)),
            "out_degree":        float(df["account_to"].nunique()),
            "in_degree":         float(df["account_from"].nunique()),
            "total_sent":        float(sent["amount"].sum()),
            "total_received":    float(recv["amount"].sum()),
            "avg_amount":        float(amounts.mean()),
            "std_amount":        float(amounts.std(ddof=0)),
            "min_amount":        float(amounts.min()),
            "max_amount":        float(amounts.max()),
            "median_amount":     float(amounts.median()),
            "sent_count":        float(len(sent)),
            "recv_count":        float(len(recv)),
            "unique_counterparts": float(
                pd.concat([sent["account_to"], recv["account_from"]]).nunique()
            ),
            "avg_sent":          float(sent["amount"].mean()) if len(sent) else 0.0,
            "avg_recv":          float(recv["amount"].mean()) if len(recv) else 0.0,
            "max_sent":          float(sent["amount"].max()) if len(sent) else 0.0,
            "max_recv":          float(recv["amount"].max()) if len(recv) else 0.0,
            "fraud_flag":        float(df["is_fraud"].any()),
            "tx_type_transfer":  float((df["tx_type"] == "TRANSFER").sum()),
            "tx_type_cashout":   float((df["tx_type"] == "CASH_OUT").sum()),
            "tx_type_payment":   float((df["tx_type"] == "PAYMENT").sum()),
            "active_days":       float(
                (df["timestamp"].max() - df["timestamp"].min()).days + 1
            ) if len(df) > 1 else 1.0,
            "tx_velocity":       float(len(df)) / max(
                (df["timestamp"].max() - df["timestamp"].min()).days + 1, 1
            ),
        }
        return feats

    def build_temporal_sequence(
        self,
        account_id: str,
        max_seq_len: int = 64,
    ) -> np.ndarray:
        """
        Build a (T, d_tx + d_macro) sequence tensor for the temporal branch.

        Per-timestep features:
          TX (d=15): amount, is_sent, is_recv, type_oh(5), balance_delta,
                     ncua_cc_rate, rate_mom_delta, log_amount, hour_sin, hour_cos,
                     day_of_week_sin, day_of_week_cos
          Macro (d=3): ncua_cc_rate, rate_mom_delta, rate_quartile
        Total d = 18

        Returns array of shape (T, 18), truncated/padded to max_seq_len.
        """
        df = self._get_account_txs(account_id)
        if df.empty:
            return np.zeros((1, 18), dtype=np.float32)

        df = self.interpolate_macro(df)
        df = df.sort_values("timestamp").tail(max_seq_len)

        rows = []
        for _, row in df.iterrows():
            is_sent = float(row["account_from"] == account_id)
            is_recv = float(row["account_to"] == account_id)
            ts: pd.Timestamp = pd.Timestamp(row["timestamp"])
            hour = ts.hour
            dow = ts.dayofweek
            rate = float(row.get("ncua_cc_rate", 0.0))
            delta = float(row.get("rate_mom_delta", 0.0))
            # Quartile of the rate relative to its long-run range [14, 22]
            rate_quartile = float(np.clip((rate - 14.0) / 8.0, 0.0, 1.0))

            # One-hot for tx_type (CASH_IN, CASH_OUT, DEBIT, PAYMENT, TRANSFER)
            tx_type = str(row.get("tx_type", ""))
            type_oh = [
                float(tx_type == "CASH_IN"),
                float(tx_type == "CASH_OUT"),
                float(tx_type == "DEBIT"),
                float(tx_type == "PAYMENT"),
                float(tx_type == "TRANSFER"),
            ]

            amount = float(row["amount"])
            feat = [
                amount / 1e6,               # normalised amount
                is_sent,
                is_recv,
                *type_oh,                   # 5 dims
                np.log1p(amount) / 20.0,    # log amount
                np.sin(2 * np.pi * hour / 24),
                np.cos(2 * np.pi * hour / 24),
                np.sin(2 * np.pi * dow / 7),
                np.cos(2 * np.pi * dow / 7),
                rate / 25.0,                # macro: normalised rate
                delta / 2.0,                # macro: normalised delta
                rate_quartile,              # macro: position in rate cycle
            ]
            rows.append(feat)

        arr = np.array(rows, dtype=np.float32)
        # Pad with zeros if shorter than max_seq_len
        if len(arr) < max_seq_len:
            pad = np.zeros((max_seq_len - len(arr), arr.shape[1]), dtype=np.float32)
            arr = np.vstack([pad, arr])
        return arr  # shape (max_seq_len, 18)

    def build_node_features(
        self,
        account_id: str,
        max_seq_len: int = 64,
    ) -> dict[str, Any]:
        """
        Full feature bundle for a single account.

        Returns
        -------
        {
          "stat_features": dict[str, float]  (23 values)
          "temporal_seq":  np.ndarray (max_seq_len, 18)
          "account_id":    str
          "tx_count":      int
        }
        """
        stat = self.build_statistical_features(account_id)
        seq = self.build_temporal_sequence(account_id, max_seq_len)
        return {
            "account_id":   account_id,
            "stat_features": stat,
            "temporal_seq":  seq,
            "tx_count":      int(stat.get("tx_count", 0)),
        }

    # ------------------------------------------------------------------
    # Batch feature extraction  (replaces 26 000 individual DuckDB queries)
    # ------------------------------------------------------------------

    def build_stat_features_batch(
        self, account_ids: list[str]
    ) -> dict[str, dict[str, float]]:
        """
        Compute statistical features for many accounts in ONE SQL query.
        ~100× faster than calling build_statistical_features in a loop.
        """
        if not account_ids:
            return {}

        _ids_df = pd.DataFrame({"acct_id": account_ids})
        self.con.execute(
            "CREATE OR REPLACE TEMP TABLE _stat_accts AS SELECT acct_id FROM _ids_df"
        )

        df = self.con.execute("""
            SELECT
                acct,
                COUNT(*)                                                        AS tx_count,
                COUNT(DISTINCT CASE WHEN is_sent THEN counterpart END)          AS out_degree,
                COUNT(DISTINCT CASE WHEN NOT is_sent THEN counterpart END)      AS in_degree,
                COALESCE(SUM(CASE WHEN is_sent THEN amount ELSE 0 END), 0)      AS total_sent,
                COALESCE(SUM(CASE WHEN NOT is_sent THEN amount ELSE 0 END), 0)  AS total_received,
                COALESCE(AVG(amount), 0)                                        AS avg_amount,
                COALESCE(STDDEV_POP(amount), 0)                                 AS std_amount,
                COALESCE(MIN(amount), 0)                                        AS min_amount,
                COALESCE(MAX(amount), 0)                                        AS max_amount,
                COALESCE(MEDIAN(amount), 0)                                     AS median_amount,
                COUNT(CASE WHEN is_sent     THEN 1 END)                         AS sent_count,
                COUNT(CASE WHEN NOT is_sent THEN 1 END)                         AS recv_count,
                COUNT(DISTINCT counterpart)                                     AS unique_counterparts,
                COALESCE(AVG(CASE WHEN is_sent     THEN amount END), 0)         AS avg_sent,
                COALESCE(AVG(CASE WHEN NOT is_sent THEN amount END), 0)         AS avg_recv,
                COALESCE(MAX(CASE WHEN is_sent     THEN amount END), 0)         AS max_sent,
                COALESCE(MAX(CASE WHEN NOT is_sent THEN amount END), 0)         AS max_recv,
                MAX(CASE WHEN is_fraud THEN 1 ELSE 0 END)                       AS fraud_flag,
                COUNT(CASE WHEN tx_type = 'TRANSFER' THEN 1 END)                AS tx_type_transfer,
                COUNT(CASE WHEN tx_type = 'CASH_OUT' THEN 1 END)                AS tx_type_cashout,
                COUNT(CASE WHEN tx_type = 'PAYMENT'  THEN 1 END)                AS tx_type_payment,
                MIN(timestamp) AS ts_min,
                MAX(timestamp) AS ts_max
            FROM (
                SELECT account_from AS acct, account_to AS counterpart,
                       amount, tx_type, is_fraud, timestamp, TRUE AS is_sent
                FROM transactions
                WHERE account_from IN (SELECT acct_id FROM _stat_accts)
                UNION ALL
                SELECT account_to AS acct, account_from AS counterpart,
                       amount, tx_type, is_fraud, timestamp, FALSE AS is_sent
                FROM transactions
                WHERE account_to IN (SELECT acct_id FROM _stat_accts)
            )
            GROUP BY acct
        """).df()

        df["active_days"] = (
            (df["ts_max"] - df["ts_min"]).dt.total_seconds() / 86400 + 1
        ).clip(lower=1).fillna(1)
        df["tx_velocity"] = (df["tx_count"] / df["active_days"]).fillna(0)
        df = df.fillna(0)

        result: dict[str, dict[str, float]] = {}
        for _, row in df.iterrows():
            acct = row["acct"]
            result[acct] = {
                "tx_count":            float(row["tx_count"]),
                "out_degree":          float(row["out_degree"]),
                "in_degree":           float(row["in_degree"]),
                "total_sent":          float(row["total_sent"]),
                "total_received":      float(row["total_received"]),
                "avg_amount":          float(row["avg_amount"]),
                "std_amount":          float(row["std_amount"]),
                "min_amount":          float(row["min_amount"]),
                "max_amount":          float(row["max_amount"]),
                "median_amount":       float(row["median_amount"]),
                "sent_count":          float(row["sent_count"]),
                "recv_count":          float(row["recv_count"]),
                "unique_counterparts": float(row["unique_counterparts"]),
                "avg_sent":            float(row["avg_sent"]),
                "avg_recv":            float(row["avg_recv"]),
                "max_sent":            float(row["max_sent"]),
                "max_recv":            float(row["max_recv"]),
                "fraud_flag":          float(row["fraud_flag"]),
                "tx_type_transfer":    float(row["tx_type_transfer"]),
                "tx_type_cashout":     float(row["tx_type_cashout"]),
                "tx_type_payment":     float(row["tx_type_payment"]),
                "active_days":         float(row["active_days"]),
                "tx_velocity":         float(row["tx_velocity"]),
            }

        empty = {f: 0.0 for f in _STAT_FEATURE_NAMES}
        for aid in account_ids:
            result.setdefault(aid, dict(empty))

        return result

    def build_temporal_sequences_batch(
        self, account_ids: list[str], max_seq_len: int = 64
    ) -> dict[str, np.ndarray]:
        """
        Build temporal feature sequences for many accounts in ONE SQL query
        + vectorized numpy — no per-account DuckDB round-trips.
        """
        if not account_ids:
            return {}

        _ids_df = pd.DataFrame({"acct_id": account_ids})
        self.con.execute(
            "CREATE OR REPLACE TEMP TABLE _temp_accts AS SELECT acct_id FROM _ids_df"
        )

        df = self.con.execute("""
            SELECT account_from, account_to, amount, tx_type, is_fraud, timestamp
            FROM transactions
            WHERE account_from IN (SELECT acct_id FROM _temp_accts)
               OR account_to   IN (SELECT acct_id FROM _temp_accts)
            ORDER BY timestamp
        """).df()

        D_FEAT = 16   # matches build_temporal_sequence output
        zero_seq = np.zeros((max_seq_len, D_FEAT), dtype=np.float32)

        if df.empty:
            return {aid: zero_seq.copy() for aid in account_ids}

        df = df.reset_index(drop=True)
        df = self.interpolate_macro(df)

        ts   = pd.to_datetime(df["timestamp"])
        amt  = df["amount"].values.astype(np.float64)
        rate = df["ncua_cc_rate"].fillna(0).values
        delt = df["rate_mom_delta"].fillna(0).values

        feat_matrix = np.column_stack([
            amt / 1e6,
            np.zeros(len(df)),                                    # is_sent (filled per-account)
            np.zeros(len(df)),                                    # is_recv (filled per-account)
            (df["tx_type"] == "CASH_IN").astype(np.float32),
            (df["tx_type"] == "CASH_OUT").astype(np.float32),
            (df["tx_type"] == "DEBIT").astype(np.float32),
            (df["tx_type"] == "PAYMENT").astype(np.float32),
            (df["tx_type"] == "TRANSFER").astype(np.float32),
            np.log1p(amt) / 20.0,
            np.sin(2 * np.pi * ts.dt.hour.values / 24),
            np.cos(2 * np.pi * ts.dt.hour.values / 24),
            np.sin(2 * np.pi * ts.dt.dayofweek.values / 7),
            np.cos(2 * np.pi * ts.dt.dayofweek.values / 7),
            rate / 25.0,
            delt / 2.0,
            np.clip((rate - 14.0) / 8.0, 0.0, 1.0),
        ]).astype(np.float32)

        ts_vals = df["timestamp"].values

        acct_set = set(account_ids)
        sent_idx_map: dict[str, list[int]] = {}
        recv_idx_map: dict[str, list[int]] = {}
        for i, (frm, to) in enumerate(zip(df["account_from"].values, df["account_to"].values)):
            if frm in acct_set:
                sent_idx_map.setdefault(frm, []).append(i)
            if to in acct_set:
                recv_idx_map.setdefault(to, []).append(i)

        result: dict[str, np.ndarray] = {}
        for aid in account_ids:
            s_idx = sent_idx_map.get(aid, [])
            r_idx = recv_idx_map.get(aid, [])
            if not s_idx and not r_idx:
                result[aid] = zero_seq.copy()
                continue

            parts_feats = []
            parts_ts    = []
            if s_idx:
                sf = feat_matrix[s_idx].copy()
                sf[:, 1] = 1.0
                parts_feats.append(sf)
                parts_ts.append(ts_vals[s_idx])
            if r_idx:
                rf = feat_matrix[r_idx].copy()
                rf[:, 2] = 1.0
                parts_feats.append(rf)
                parts_ts.append(ts_vals[r_idx])

            all_feats = np.vstack(parts_feats)
            all_ts    = np.concatenate(parts_ts)
            order     = np.argsort(all_ts)
            all_feats = all_feats[order][-max_seq_len:]

            n = len(all_feats)
            if n < max_seq_len:
                pad = np.zeros((max_seq_len - n, D_FEAT), dtype=np.float32)
                all_feats = np.vstack([pad, all_feats])

            result[aid] = all_feats

        return result

    def build_node_features_batch(
        self, account_ids: list[str], max_seq_len: int = 64
    ) -> dict[str, Any]:
        """Batch build of the full feature bundle (stat + temporal) for many accounts."""
        stat_batch = self.build_stat_features_batch(account_ids)
        temp_batch = self.build_temporal_sequences_batch(account_ids, max_seq_len)
        empty_stat = {f: 0.0 for f in _STAT_FEATURE_NAMES}
        D_FEAT = 16
        return {
            aid: {
                "account_id":    aid,
                "stat_features": stat_batch.get(aid, dict(empty_stat)),
                "temporal_seq":  temp_batch.get(
                    aid, np.zeros((max_seq_len, D_FEAT), dtype=np.float32)
                ),
                "tx_count": int(stat_batch.get(aid, empty_stat).get("tx_count", 0)),
            }
            for aid in account_ids
        }

    # ------------------------------------------------------------------
    # Clique persistence
    # ------------------------------------------------------------------

    def write_cliques(self, window_id: str, window_start, window_end, cliques: list[list[str]]) -> None:
        self.con.execute("DELETE FROM cliques WHERE window_id = ?", [window_id])
        rows = [
            (window_id, window_start, window_end, json.dumps(c), len(c))
            for c in cliques
        ]
        self.con.executemany(
            "INSERT INTO cliques VALUES (?, ?, ?, ?, ?)", rows
        )

    def get_cliques_for_account(self, account_id: str) -> list[list[str]]:
        """Return all cliques that contain this account."""
        # DuckDB JSON array search — use Python-side scan (portable across versions)
        rows = self.con.execute("SELECT clique_members FROM cliques").fetchall()
        result = []
        for (members_json,) in rows:
            try:
                members = json.loads(members_json)
                if account_id in members:
                    result.append(members)
            except Exception:
                continue
        return result

    # ------------------------------------------------------------------
    # Risk score persistence
    # ------------------------------------------------------------------

    def write_risk_score(
        self,
        account_id: str,
        risk_score: float,
        flags: list[str],
    ) -> None:
        label = (
            "HIGH" if risk_score >= 0.70
            else "MEDIUM" if risk_score >= 0.40
            else "LOW"
        )
        self.con.execute("DELETE FROM risk_scores WHERE account_id = ?", [account_id])
        self.con.execute("""
            INSERT INTO risk_scores VALUES (?, ?, ?, ?, ?)
        """, [account_id, risk_score, label, json.dumps(flags), datetime.utcnow()])

    def get_risk_score(self, account_id: str) -> dict[str, Any] | None:
        """Return stored risk info or None if account not yet analysed."""
        row = self.con.execute("""
            SELECT account_id, risk_score, risk_label, flags_json, analyzed_at
            FROM risk_scores WHERE account_id = ?
        """, [account_id]).fetchone()
        if row is None:
            return None
        return {
            "account_id":  row[0],
            "risk_score":  row[1],
            "risk_label":  row[2],
            "flags":       json.loads(row[3]) if row[3] else [],
            "analyzed_at": row[4],
        }

    # ------------------------------------------------------------------
    # Graph helpers (for Pyvis / hyperedge building)
    # ------------------------------------------------------------------

    def get_ego_network(
        self,
        account_id: str,
        hops: int = 2,
        max_nodes: int = 150,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Extract the ego network (up to `hops` hops) around account_id.

        Returns (nodes_df, edges_df) where:
          nodes_df : account_id, tx_count, is_fraud_any, risk_score
          edges_df : source, target, total_amount, tx_count
        """
        visited = {account_id}
        frontier = {account_id}

        for _ in range(hops):
            if len(visited) >= max_nodes:
                break
            if not frontier:
                break
            placeholders = ",".join(["?"] * len(frontier))
            nbrs = self.con.execute(f"""
                SELECT DISTINCT account_from AS nbr FROM transactions
                WHERE account_to IN ({placeholders})
                UNION
                SELECT DISTINCT account_to AS nbr FROM transactions
                WHERE account_from IN ({placeholders})
            """, list(frontier) * 2).fetchall()
            new_nodes = {r[0] for r in nbrs} - visited
            new_nodes = set(list(new_nodes)[: max_nodes - len(visited)])
            visited |= new_nodes
            frontier = new_nodes

        all_ids = list(visited)
        ph = ",".join(["?"] * len(all_ids))

        edges_df = self.con.execute(f"""
            SELECT
                account_from AS source,
                account_to   AS target,
                SUM(amount)  AS total_amount,
                COUNT(*)     AS tx_count
            FROM transactions
            WHERE account_from IN ({ph}) AND account_to IN ({ph})
            GROUP BY account_from, account_to
        """, all_ids * 2).df()

        # Node stats
        node_rows = []
        for aid in all_ids:
            stat = self.build_statistical_features(aid)
            score_row = self.get_risk_score(aid)
            node_rows.append({
                "account_id":   aid,
                "tx_count":     int(stat["tx_count"]),
                "is_fraud_any": bool(stat["fraud_flag"]),
                "risk_score":   score_row["risk_score"] if score_row else 0.5,
            })
        nodes_df = pd.DataFrame(node_rows)
        return nodes_df, edges_df

    def get_monthly_activity(self, account_id: str) -> pd.DataFrame:
        """
        Return monthly transaction volume for an account, joined with NCUA rate.
        Used by the macro overlay chart (Panel 3).
        """
        df = self.con.execute("""
            SELECT
                date_trunc('month', timestamp)::DATE AS month,
                COUNT(*)                             AS tx_count,
                SUM(amount)                          AS total_volume
            FROM transactions
            WHERE account_from = ? OR account_to = ?
            GROUP BY 1
            ORDER BY 1
        """, [account_id, account_id]).df()

        macro_df = self.get_macro_df()
        macro_df["month"] = macro_df["period_date"].dt.to_period("M").dt.to_timestamp().astype("datetime64[us]")
        df["month"] = df["month"].astype("datetime64[us]")

        merged = pd.merge_asof(
            df.sort_values("month"),
            macro_df[["month", "ncua_cc_rate", "rate_mom_delta"]].sort_values("month"),
            on="month",
            direction="backward",
        )
        merged["ncua_cc_rate"] = merged["ncua_cc_rate"].ffill().fillna(0)
        return merged

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_all_accounts(self) -> list[str]:
        rows = self.con.execute("""
            SELECT DISTINCT account_from FROM transactions
            UNION
            SELECT DISTINCT account_to FROM transactions
        """).fetchall()
        return [r[0] for r in rows]

    def account_exists(self, account_id: str) -> bool:
        n = self.con.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE account_from = ? OR account_to = ?
        """, [account_id, account_id]).fetchone()[0]
        return n > 0

    def compute_macro_fraud_correlation(self) -> pd.DataFrame:
        """
        Aggregate monthly average risk score vs NCUA CC rate.
        Used for the Model Performance correlation chart.

        Returns a DataFrame with columns:
            month, avg_risk_score, high_risk_count, scored_accounts, ncua_cc_rate, rate_mom_delta
        """
        try:
            monthly = self.con.execute("""
                SELECT
                    date_trunc('month', t.timestamp)::DATE AS month,
                    AVG(r.risk_score)                      AS avg_risk_score,
                    SUM(CASE WHEN r.risk_label = 'HIGH' THEN 1 ELSE 0 END) AS high_risk_count,
                    COUNT(DISTINCT r.account_id)           AS scored_accounts
                FROM risk_scores r
                JOIN transactions t
                  ON t.account_from = r.account_id OR t.account_to = r.account_id
                GROUP BY 1
                ORDER BY 1
            """).df()
        except Exception:
            return pd.DataFrame()

        if monthly.empty:
            return monthly

        macro_df = self.get_macro_df()
        macro_df = macro_df.copy()
        macro_df["month"] = macro_df["period_date"].dt.to_period("M").dt.to_timestamp()

        merged = pd.merge_asof(
            monthly.sort_values("month"),
            macro_df[["month", "ncua_cc_rate", "rate_mom_delta"]].sort_values("month"),
            on="month",
            direction="backward",
        )
        merged["ncua_cc_rate"] = merged["ncua_cc_rate"].ffill().fillna(0)
        return merged

    def close(self) -> None:
        self.con.close()


# ---------------------------------------------------------------------------
# Feature name reference (for LightGBM column ordering)
# ---------------------------------------------------------------------------

_STAT_FEATURE_NAMES = [
    "tx_count", "out_degree", "in_degree", "total_sent", "total_received",
    "avg_amount", "std_amount", "min_amount", "max_amount", "median_amount",
    "sent_count", "recv_count", "unique_counterparts", "avg_sent", "avg_recv",
    "max_sent", "max_recv", "fraud_flag", "tx_type_transfer", "tx_type_cashout",
    "tx_type_payment", "active_days", "tx_velocity",
]
