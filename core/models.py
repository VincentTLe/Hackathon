"""
Guardian-Sleuth: FLHR-MCL Model (AML Adaptation)
==================================================
Implements the full model stack from the paper:
  Liu et al., "Ethereum phishing scam detection via multi-view contrastive
  learning on higher-order networks," ESWA 321 (2026).

Adapted for Anti-Money Laundering in fiat banking:
  - Macro-fused temporal branch: Transformer + BiLSTM with NCUA rate appended
    per timestep (d_tx + d_macro = 18-dim input)
  - GCN on pairwise transaction graph  (eq. 8)
  - HGNN on hypergraph of maximal cliques  (eq. 9)
  - Multi-view contrastive loss  (eq. 10 / 11)
  - HistGradientBoosting classifier on concatenated embeddings
    (sklearn — no OpenMP/libomp dependency; swap for LightGBM once libomp
     is installed via `brew install libomp`)

Classes
-------
MacroFusedTransformerBiLSTM   - temporal branch
GCNEncoder                     - pairwise graph branch
HGNNEncoder                    - hypergraph branch
FLHR_MCL                       - orchestrator (contrastive training)
AMLPipeline                    - end-to-end: features → risk score
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hyperparameters (paper defaults, adapted for AML)
# ---------------------------------------------------------------------------

HIDDEN_DIM    = 64
N_HEADS       = 4
N_TRANSFORMER_LAYERS = 2
BILSTM_LAYERS = 1
DROPOUT       = 0.1
MASK_RATE     = 0.2      # μ in eq. (6)
MARGIN        = 1.0      # contrastive margin in eq. (10)
LR            = 0.1
EPOCHS        = 100
GCN_LAYERS    = 2
HGNN_LAYERS   = 2

D_INPUT       = 18       # tx_features(15) + macro_features(3)
D_STAT        = 23       # statistical feature vector dimension


# ===========================================================================
# 1. Temporal branch: Macro-Fused Transformer + BiLSTM
# ===========================================================================

class MacroFusedTransformerBiLSTM(nn.Module):
    """
    Processes a per-account transaction sequence of shape (B, T, D_INPUT).

    D_INPUT = 18: 15 transaction features + 3 NCUA macro features appended
    at each timestep (ncua_cc_rate, rate_mom_delta, rate_quartile).

    Pipeline:
        Linear projection → Transformer encoder → BiLSTM → avg pool → z_v^t
    """

    def __init__(
        self,
        d_input:   int = D_INPUT,
        d_model:   int = HIDDEN_DIM,
        n_heads:   int = N_HEADS,
        n_layers:  int = N_TRANSFORMER_LAYERS,
        dropout:   float = DROPOUT,
    ):
        super().__init__()
        self.input_proj = nn.Linear(d_input, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        self.bilstm = nn.LSTM(
            input_size=d_model,
            hidden_size=d_model // 2,      # bidirectional → full hidden_dim
            num_layers=BILSTM_LAYERS,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if BILSTM_LAYERS > 1 else 0.0,
        )
        self.out_dim = d_model

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        """
        Parameters
        ----------
        x    : (B, T, D_INPUT) — batch of transaction sequences with macro context
        mask : (B, T) bool — True where padding (optional)

        Returns
        -------
        z : (B, hidden_dim) — pooled temporal embedding per account (z_v^t)
        """
        x = self.input_proj(x)                         # (B, T, d_model)
        x = self.transformer(x, src_key_padding_mask=mask)   # (B, T, d_model)
        x, _ = self.bilstm(x)                          # (B, T, d_model)

        # Average pooling over valid (non-padded) timesteps — eq. (5)
        if mask is not None:
            valid = (~mask).unsqueeze(-1).float()      # (B, T, 1)
            z = (x * valid).sum(dim=1) / valid.sum(dim=1).clamp(min=1)
        else:
            z = x.mean(dim=1)
        return z                                       # (B, d_model)


# ===========================================================================
# 2. GCN Encoder (pairwise transaction graph)
# ===========================================================================

class GCNEncoder(nn.Module):
    """
    2-layer Graph Convolutional Network on the pairwise transaction graph.
    Implements eq. (8) from the paper (symmetric normalisation).

    Operates on dense node feature matrix + adjacency; suitable for the
    sub-graphs encountered in a single time window (~100s of nodes).
    """

    def __init__(self, d_in: int = D_STAT, d_out: int = HIDDEN_DIM):
        super().__init__()
        d_mid = max(d_in, d_out)
        self.W1 = nn.Linear(d_in,  d_mid, bias=False)
        self.W2 = nn.Linear(d_mid, d_out, bias=False)
        self.bn1 = nn.BatchNorm1d(d_mid)
        self.bn2 = nn.BatchNorm1d(d_out)

    @staticmethod
    def _normalise_adj(A: torch.Tensor) -> torch.Tensor:
        """Symmetric normalisation: D^{-1/2} A D^{-1/2}"""
        A = A + torch.eye(A.size(0), device=A.device)      # add self-loops
        deg = A.sum(dim=1).clamp(min=1)
        d_inv_sqrt = deg.pow(-0.5)
        D = torch.diag(d_inv_sqrt)
        return D @ A @ D

    def forward(self, x: torch.Tensor, A: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        x : (N, d_in)  — node feature matrix
        A : (N, N)     — adjacency matrix (binary, undirected)

        Returns
        -------
        h : (N, d_out) — node embeddings
        """
        A_hat = self._normalise_adj(A)
        h = F.relu(self.bn1(self.W1(A_hat @ x)))   # layer 1
        h = F.relu(self.bn2(self.W2(A_hat @ h)))   # layer 2
        return h                                    # (N, d_out)


# ===========================================================================
# 3. HGNN Encoder (hypergraph of maximal cliques)
# ===========================================================================

class HGNNEncoder(nn.Module):
    """
    Hypergraph Neural Network encoder.
    Implements eq. (9): hypergraph convolution via incidence matrix H.

    Input features per node: statistical features + hyperedge size feature.
    Processes all hyperedges (cliques) found by the C++ Bron-Kerbosch engine.
    """

    def __init__(self, d_in: int = D_STAT + 1, d_out: int = HIDDEN_DIM):
        super().__init__()
        d_mid = max(d_in, d_out)
        self.W1 = nn.Linear(d_in,  d_mid, bias=False)
        self.W2 = nn.Linear(d_mid, d_out, bias=False)
        self.bn1 = nn.BatchNorm1d(d_mid)
        self.bn2 = nn.BatchNorm1d(d_out)

    @staticmethod
    def _build_theta(H: torch.Tensor) -> torch.Tensor:
        """
        Compute the symmetric hypergraph Laplacian propagation matrix.
        Θ = D_v^{-1/2} H W D_e^{-1} H^T D_v^{-1/2}
        where W = I (unit hyperedge weights), D_v = node degrees, D_e = edge degrees.
        """
        D_e = H.sum(dim=0).clamp(min=1)             # (E,)
        D_v = H.sum(dim=1).clamp(min=1)             # (N,)
        D_v_inv_sqrt = D_v.pow(-0.5)
        # Θ = diag(D_v^{-1/2}) @ H @ diag(D_e^{-1}) @ H^T @ diag(D_v^{-1/2})
        HW = H / D_e.unsqueeze(0)                   # (N, E)
        Theta = torch.diag(D_v_inv_sqrt) @ HW @ H.T @ torch.diag(D_v_inv_sqrt)
        return Theta

    def forward(self, x: torch.Tensor, H: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        x : (N, d_in)  — node feature matrix (stat_features + clique_size_feature)
        H : (N, E)     — incidence matrix (H[i, e] = 1 if node i in hyperedge e)

        Returns
        -------
        p : (N, d_out) — higher-order node embeddings
        """
        if H.shape[1] == 0:
            # No hyperedges in this window — return zeros
            return torch.zeros(x.shape[0], self.W2.out_features, device=x.device)

        Theta = self._build_theta(H)
        p = F.relu(self.bn1(self.W1(Theta @ x)))   # layer 1
        p = F.relu(self.bn2(self.W2(Theta @ p)))   # layer 2
        return p                                    # (N, d_out)


# ===========================================================================
# 4. Adaptive feature masking (eq. 6 / 7)
# ===========================================================================

def adaptive_mask(
    x: torch.Tensor,
    tx_counts: torch.Tensor,
    mu: float = MASK_RATE,
) -> torch.Tensor:
    """
    Apply adaptive feature masking (eq. 6 / 7 from paper).
    Nodes with fewer transactions get a higher masking probability.

    Parameters
    ----------
    x          : (N, d) — node features
    tx_counts  : (N,)   — number of transactions per node
    mu         : base masking rate

    Returns
    -------
    x_masked : (N, d)
    """
    T_max = tx_counts.max().clamp(min=1).float()
    p_mask = mu * (1.0 - tx_counts.float() / T_max)   # eq. (6)
    mask = torch.bernoulli(p_mask.unsqueeze(1).expand_as(x))
    return x * (1.0 - mask)                            # eq. (7)


# ===========================================================================
# 5. Contrastive loss (eq. 10 / 11)
# ===========================================================================

def contrastive_loss(
    z1: torch.Tensor,
    z2: torch.Tensor,
    margin: float = MARGIN,
) -> torch.Tensor:
    """
    Pair-wise contrastive loss (eq. 10).

    L = (1/N) Σ (1 - sim(z_i, z'_i))
      + (1/N(N-1)) Σ_{i≠j} max(0, sim(z_i, z_j) - margin)

    Positive pairs: (z1[i], z2[i]) — same node, different augmentation/view.
    Negative pairs: (z1[i], z1[j]) for i ≠ j.
    """
    z1n = F.normalize(z1, dim=-1)
    z2n = F.normalize(z2, dim=-1)

    # Positive term: maximise similarity of same-node pairs
    pos_sim = (z1n * z2n).sum(dim=-1)               # (N,)
    pos_loss = (1.0 - pos_sim).mean()

    # Negative term: push apart different-node embeddings
    sim_matrix = z1n @ z1n.T                        # (N, N)
    N = z1n.size(0)
    mask = ~torch.eye(N, dtype=torch.bool, device=z1.device)
    neg_sim = sim_matrix[mask].view(N, N - 1)
    neg_loss = F.relu(neg_sim - margin).mean()

    return pos_loss + neg_loss


# ===========================================================================
# 6. FLHR_MCL Orchestrator
# ===========================================================================

class FLHR_MCL(nn.Module):
    """
    Full FLHR-MCL model for a single time window.

    Forward pass:
      1. GCN on original graph → z_GCN
      2. HGNN on hypergraph → z_HGNN
      3. Masked versions → z'_GCN, z'_HGNN
      4. Total contrastive loss (eq. 11):
             L_total = L(GCN, GCN') + L(HGNN, HGNN') + L(GCN, HGNN)
      5. Returns concatenated embeddings for downstream LightGBM.
    """

    def __init__(
        self,
        d_stat:  int   = D_STAT,
        d_model: int   = HIDDEN_DIM,
        mu:      float = MASK_RATE,
        margin:  float = MARGIN,
    ):
        super().__init__()
        self.gcn  = GCNEncoder(d_in=d_stat,     d_out=d_model)
        self.hgnn = HGNNEncoder(d_in=d_stat + 1, d_out=d_model)  # +1 for clique_size
        self.mu     = mu
        self.margin = margin

    def forward(
        self,
        x_stat:    torch.Tensor,   # (N, D_STAT)
        A:         torch.Tensor,   # (N, N) pairwise adjacency
        H:         torch.Tensor,   # (N, E) hyperedge incidence
        tx_counts: torch.Tensor,   # (N,)   per-node tx count for masking
        clique_sizes: torch.Tensor,# (N,)   avg clique size per node (HGNN extra feature)
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Returns
        -------
        (embeddings, loss)
        embeddings : (N, 2 * d_model) — concat[z_GCN, z_HGNN]
        loss       : scalar            — total contrastive loss
        """
        # Augmented views via adaptive masking
        x_masked_gcn  = adaptive_mask(x_stat, tx_counts, self.mu)
        x_masked_hgnn = adaptive_mask(x_stat, tx_counts, self.mu)

        # HGNN input: stat features + per-node avg clique size feature
        x_hgnn        = torch.cat([x_stat,        clique_sizes.unsqueeze(1)], dim=1)
        x_masked_hgnn = torch.cat([x_masked_hgnn, clique_sizes.unsqueeze(1)], dim=1)

        z_gcn   = self.gcn(x_stat, A)             # (N, d)
        z_gcn_m = self.gcn(x_masked_gcn, A)       # (N, d)  augmented
        z_hgnn  = self.hgnn(x_hgnn, H)            # (N, d)
        z_hgnn_m = self.hgnn(x_masked_hgnn, H)    # (N, d)  augmented

        # Three contrastive terms (eq. 11)
        loss = (
            contrastive_loss(z_gcn,  z_gcn_m,  self.margin)
            + contrastive_loss(z_hgnn, z_hgnn_m, self.margin)
            + contrastive_loss(z_gcn,  z_hgnn,   self.margin)
        )

        embeddings = torch.cat([z_gcn, z_hgnn], dim=1)  # (N, 2*d)
        return embeddings, loss


# ===========================================================================
# 7. End-to-end AML Pipeline
# ===========================================================================

class AMLPipeline:
    """
    Orchestrates the full training and inference pipeline:
      1. Build graph / hypergraph from the time-windowed transaction data
      2. Train FLHR_MCL (contrastive pre-training)
      3. Extract node embeddings
      4. Concatenate with statistical features
      5. Train LightGBM classifier
      6. Produce per-account risk scores [0, 1]

    Parameters
    ----------
    device      : torch device ('cpu' or 'cuda')
    hidden_dim  : embedding dimension
    epochs      : contrastive training epochs
    lr          : learning rate
    """

    def __init__(
        self,
        device:     str = "cpu",
        hidden_dim: int = HIDDEN_DIM,
        epochs:     int = EPOCHS,
        lr:         float = LR,
    ):
        self.device     = torch.device(device)
        self.hidden_dim = hidden_dim
        self.epochs     = epochs
        self.lr         = lr
        self.scaler     = StandardScaler()
        self.lgbm_model: HistGradientBoostingClassifier | None = None
        self.flhr_mcl:   FLHR_MCL | None = None
        self.temporal_branch: MacroFusedTransformerBiLSTM | None = None
        self._test_metrics: dict = {}

    # ------------------------------------------------------------------
    # Graph construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_adjacency(
        account_ids: list[str],
        tx_df: "pd.DataFrame",
    ) -> torch.Tensor:
        """Build symmetric (N, N) binary adjacency matrix from transactions."""
        idx = {a: i for i, a in enumerate(account_ids)}
        N = len(account_ids)
        A = torch.zeros(N, N)
        for _, row in tx_df.iterrows():
            u = idx.get(row["account_from"])
            v = idx.get(row["account_to"])
            if u is not None and v is not None:
                A[u, v] = 1.0
                A[v, u] = 1.0
        return A

    @staticmethod
    def build_incidence(
        account_ids: list[str],
        cliques:     list[list[str]],
    ) -> torch.Tensor:
        """Build (N, E) incidence matrix H from lists of cliques."""
        idx = {a: i for i, a in enumerate(account_ids)}
        N = len(account_ids)
        E = len(cliques)
        if E == 0:
            return torch.zeros(N, 0)
        H = torch.zeros(N, E)
        for e, clique in enumerate(cliques):
            for node in clique:
                i = idx.get(node)
                if i is not None:
                    H[i, e] = 1.0
        return H

    @staticmethod
    def node_clique_sizes(
        account_ids: list[str],
        cliques:     list[list[str]],
    ) -> torch.Tensor:
        """For each node, compute the mean size of cliques it belongs to."""
        idx = {a: i for i, a in enumerate(account_ids)}
        sizes = torch.zeros(len(account_ids))
        counts = torch.zeros(len(account_ids))
        for clique in cliques:
            sz = len(clique)
            for node in clique:
                i = idx.get(node)
                if i is not None:
                    sizes[i] += sz
                    counts[i] += 1
        counts = counts.clamp(min=1)
        return sizes / counts

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        account_ids:  list[str],
        stat_matrix:  np.ndarray,       # (N, D_STAT)
        temporal_seqs: np.ndarray,      # (N, T, 18)
        tx_counts:    np.ndarray,       # (N,)
        tx_df:        "pd.DataFrame",
        cliques:      list[list[str]],
        labels:       np.ndarray,       # (N,) binary fraud labels
    ) -> dict:
        """
        Full training run.

        Returns a dict with training metrics.
        """
        N = len(account_ids)
        logger.info("Training FLHR-MCL on %d accounts, %d cliques", N, len(cliques))

        # ---- Build graph structures ----
        A = self.build_adjacency(account_ids, tx_df).to(self.device)
        H = self.build_incidence(account_ids, cliques).to(self.device)
        cs = self.node_clique_sizes(account_ids, cliques).to(self.device)
        tx_t = torch.tensor(tx_counts, dtype=torch.float32).to(self.device)
        X_stat = torch.tensor(stat_matrix, dtype=torch.float32).to(self.device)
        X_temp = torch.tensor(temporal_seqs, dtype=torch.float32).to(self.device)

        # ---- Temporal branch ----
        self.temporal_branch = MacroFusedTransformerBiLSTM(
            d_input=X_temp.shape[-1], d_model=self.hidden_dim
        ).to(self.device)

        # ---- FLHR_MCL contrastive module ----
        self.flhr_mcl = FLHR_MCL(
            d_stat=stat_matrix.shape[1], d_model=self.hidden_dim
        ).to(self.device)

        params = (
            list(self.temporal_branch.parameters())
            + list(self.flhr_mcl.parameters())
        )
        optimizer = torch.optim.Adam(params, lr=self.lr)

        # ---- Contrastive pre-training ----
        self.temporal_branch.train()
        self.flhr_mcl.train()
        losses = []

        for epoch in range(self.epochs):
            optimizer.zero_grad()
            z_temp = self.temporal_branch(X_temp)           # (N, hidden_dim)
            graph_embeddings, graph_loss = self.flhr_mcl(X_stat, A, H, tx_t, cs)
            # Align temporal embeddings with graph embeddings via cross-view loss
            temp_loss = contrastive_loss(z_temp, graph_embeddings[:, :self.hidden_dim])
            loss = graph_loss + temp_loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, max_norm=5.0)
            optimizer.step()
            losses.append(loss.item())
            if (epoch + 1) % 20 == 0:
                logger.info("Epoch %d/%d  loss=%.4f", epoch + 1, self.epochs, loss.item())

        # ---- Extract final node embeddings ----
        embeddings = self._get_embeddings(X_stat, X_temp, A, H, tx_t, cs)

        # ---- Concatenate: stat + temporal + graph ----
        X_lgbm = np.hstack([stat_matrix, embeddings])
        X_lgbm = self.scaler.fit_transform(X_lgbm)

        # ---- Train HGBT classifier with 80/20 holdout + 5-fold CV ----
        # Using sklearn HistGradientBoostingClassifier (no libomp dependency).
        # Swap for lgb.LGBMClassifier once `brew install libomp` is run.
        self.lgbm_model = HistGradientBoostingClassifier(
            max_iter=500,
            learning_rate=0.03,
            max_depth=6,
            max_leaf_nodes=31,
            min_samples_leaf=20,
            l2_regularization=0.1,
            class_weight="balanced",
            random_state=42,
        )

        # 80/20 stratified holdout — test set is never seen during CV
        try:
            X_train80, X_test20, y_train80, y_test20 = train_test_split(
                X_lgbm, labels, test_size=0.2, random_state=42, stratify=labels
            )
        except ValueError:
            X_train80, X_test20, y_train80, y_test20 = train_test_split(
                X_lgbm, labels, test_size=0.2, random_state=42
            )

        # 5-fold CV on the 80% training split
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        oof_scores: list[float] = []
        for fold, (tr_idx, val_idx) in enumerate(skf.split(X_train80, y_train80)):
            self.lgbm_model.fit(X_train80[tr_idx], y_train80[tr_idx])
            preds = self.lgbm_model.predict_proba(X_train80[val_idx])[:, 1]
            f1 = f1_score(y_train80[val_idx], preds >= 0.5, zero_division=0)
            oof_scores.append(f1)
            logger.info("Fold %d F1=%.4f", fold + 1, f1)

        avg_cv_f1 = float(np.mean(oof_scores))
        logger.info("Average cross-val F1 (80%% train): %.4f", avg_cv_f1)

        # Evaluate on held-out 20% test set
        self.lgbm_model.fit(X_train80, y_train80)
        test_probs  = self.lgbm_model.predict_proba(X_test20)[:, 1]
        test_binary = test_probs >= 0.5
        try:
            test_auc = float(roc_auc_score(y_test20, test_probs))
        except ValueError:
            test_auc = 0.0

        self._test_metrics = {
            "test_f1":        float(f1_score(y_test20, test_binary, zero_division=0)),
            "test_accuracy":  float(accuracy_score(y_test20, test_binary)),
            "test_auc":       test_auc,
            "test_precision": float(precision_score(y_test20, test_binary, zero_division=0)),
            "test_recall":    float(recall_score(y_test20, test_binary, zero_division=0)),
            "train_cv_f1":    avg_cv_f1,
            "test_size":      int(len(y_test20)),
            "train_size":     int(len(y_train80)),
        }
        logger.info(
            "Test-set (20%%) — Accuracy=%.4f  F1=%.4f  AUC=%.4f  Precision=%.4f  Recall=%.4f",
            self._test_metrics["test_accuracy"],
            self._test_metrics["test_f1"],
            self._test_metrics["test_auc"],
            self._test_metrics["test_precision"],
            self._test_metrics["test_recall"],
        )

        # Final production model trained on ALL data
        self.lgbm_model.fit(X_lgbm, labels)

        return {
            "avg_f1":              avg_cv_f1,
            "contrastive_losses":  losses,
            **self._test_metrics,
        }

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    @torch.no_grad()
    def _get_embeddings(
        self,
        X_stat: torch.Tensor,
        X_temp: torch.Tensor,
        A:      torch.Tensor,
        H:      torch.Tensor,
        tx_t:   torch.Tensor,
        cs:     torch.Tensor,
    ) -> np.ndarray:
        self.temporal_branch.eval()   # type: ignore[union-attr]
        self.flhr_mcl.eval()          # type: ignore[union-attr]
        z_temp = self.temporal_branch(X_temp).cpu().numpy()
        z_graph, _ = self.flhr_mcl(X_stat, A, H, tx_t, cs)
        z_graph = z_graph.cpu().numpy()
        return np.hstack([z_temp, z_graph])   # (N, hidden + 2*hidden)

    @torch.no_grad()
    def predict(
        self,
        account_ids:  list[str],
        stat_matrix:  np.ndarray,
        temporal_seqs: np.ndarray,
        tx_counts:    np.ndarray,
        tx_df:        "pd.DataFrame",
        cliques:      list[list[str]],
    ) -> np.ndarray:
        """
        Predict risk scores for a list of accounts.

        Returns np.ndarray of shape (N,) with values in [0, 1].
        """
        if self.lgbm_model is None:
            raise RuntimeError("Call fit() before predict()")

        A  = self.build_adjacency(account_ids, tx_df).to(self.device)
        H  = self.build_incidence(account_ids, cliques).to(self.device)
        cs = self.node_clique_sizes(account_ids, cliques).to(self.device)
        tx_t  = torch.tensor(tx_counts, dtype=torch.float32).to(self.device)
        X_s   = torch.tensor(stat_matrix,    dtype=torch.float32).to(self.device)
        X_t   = torch.tensor(temporal_seqs,  dtype=torch.float32).to(self.device)

        embeddings = self._get_embeddings(X_s, X_t, A, H, tx_t, cs)
        X_lgbm = np.hstack([stat_matrix, embeddings])
        X_lgbm = self.scaler.transform(X_lgbm)
        return self.lgbm_model.predict_proba(X_lgbm)[:, 1]

    def predict_single(
        self,
        account_id:   str,
        stat_features: dict,
        temporal_seq:  np.ndarray,
        tx_count:      int,
        tx_df:         "pd.DataFrame",
        cliques:       list[list[str]],
    ) -> float:
        """Convenience wrapper for single-account inference."""
        from core.data_manager import _STAT_FEATURE_NAMES
        stat_vec = np.array(
            [stat_features.get(f, 0.0) for f in _STAT_FEATURE_NAMES],
            dtype=np.float32,
        )[None, :]
        temp_arr = temporal_seq[None, :, :]
        scores = self.predict(
            account_ids=[account_id],
            stat_matrix=stat_vec,
            temporal_seqs=temp_arr,
            tx_counts=np.array([tx_count], dtype=np.float32),
            tx_df=tx_df,
            cliques=cliques,
        )
        return float(scores[0])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_artifacts(self, artifact_dir: str) -> None:
        """
        Persist all trained components to disk so the app loads instantly.
        Call this once after fit() during pre-training.
        """
        import json as _json
        import joblib
        from pathlib import Path

        Path(artifact_dir).mkdir(parents=True, exist_ok=True)

        # sklearn classifier + scaler
        joblib.dump(self.lgbm_model, f"{artifact_dir}/hgbt.joblib")
        joblib.dump(self.scaler,     f"{artifact_dir}/scaler.joblib")

        # PyTorch state dicts
        torch.save(self.temporal_branch.state_dict(), f"{artifact_dir}/temporal_branch.pt")
        torch.save(self.flhr_mcl.state_dict(),        f"{artifact_dir}/flhr_mcl.pt")

        # Architecture metadata (needed to reconstruct modules)
        meta = {
            "hidden_dim": self.hidden_dim,
            "d_stat":     D_STAT,
            "d_input":    self.temporal_branch.input_proj.in_features,  # actual trained dim
            "epochs":     self.epochs,
            "lr":         self.lr,
        }
        with open(f"{artifact_dir}/meta.json", "w") as f:
            _json.dump(meta, f)

        # Test-set evaluation metrics (80/20 split)
        with open(f"{artifact_dir}/metrics.json", "w") as f:
            _json.dump(self._test_metrics, f)

        logger.info("Artifacts saved to %s", artifact_dir)

    @classmethod
    def load_artifacts(cls, artifact_dir: str, device: str = "cpu") -> "AMLPipeline":
        """
        Reconstruct a fully trained AMLPipeline from saved artifacts.
        Used by main.py on startup — no training required.
        """
        import json as _json
        import joblib

        with open(f"{artifact_dir}/meta.json") as f:
            meta = _json.load(f)

        pipeline = cls(device=device, hidden_dim=meta["hidden_dim"],
                       epochs=meta["epochs"], lr=meta["lr"])

        pipeline.lgbm_model = joblib.load(f"{artifact_dir}/hgbt.joblib")
        pipeline.scaler      = joblib.load(f"{artifact_dir}/scaler.joblib")

        pipeline.temporal_branch = MacroFusedTransformerBiLSTM(
            d_input=meta["d_input"], d_model=meta["hidden_dim"]
        ).to(pipeline.device)
        pipeline.temporal_branch.load_state_dict(
            torch.load(f"{artifact_dir}/temporal_branch.pt", map_location=pipeline.device)
        )
        pipeline.temporal_branch.eval()

        pipeline.flhr_mcl = FLHR_MCL(
            d_stat=meta["d_stat"], d_model=meta["hidden_dim"]
        ).to(pipeline.device)
        pipeline.flhr_mcl.load_state_dict(
            torch.load(f"{artifact_dir}/flhr_mcl.pt", map_location=pipeline.device)
        )
        pipeline.flhr_mcl.eval()

        # Load test metrics if present
        metrics_path = f"{artifact_dir}/metrics.json"
        try:
            with open(metrics_path) as f:
                pipeline._test_metrics = _json.load(f)
        except Exception:
            pipeline._test_metrics = {}

        logger.info("Artifacts loaded from %s", artifact_dir)
        return pipeline


# ===========================================================================
# 8. Behavioural flag generator (for Panel 4)
# ===========================================================================

def generate_flags(
    account_id:    str,
    risk_score:    float,
    stat_features: dict,
    cliques:       list[list[str]],
    monthly_df:    "pd.DataFrame",
) -> list[str]:
    """
    Generate plain-English behavioural red flags from model outputs.
    Used to populate Panel 4 of the analyst dashboard.
    """
    flags: list[tuple[str, str]] = []   # (severity, message)

    # --- Clique membership ---
    account_cliques = [c for c in cliques if account_id in c]
    if account_cliques:
        max_sz = max(len(c) for c in account_cliques)
        flags.append(("🔴", f"Account is part of a tightly-coupled {max_sz}-node transfer clique"))
        if max_sz >= 5:
            flags.append(("🔴", "Large clique size (≥5) is a strong indicator of syndicate laundering"))

    # --- Structuring (many sub-threshold transfers) ---
    avg_amt = stat_features.get("avg_amount", 0)
    tx_count = stat_features.get("tx_count", 0)
    if avg_amt < 9_500 and tx_count > 20:
        flags.append(("🔴", "Structuring pattern detected: repeated sub-threshold transfers (< $10,000)"))

    # --- High velocity ---
    velocity = stat_features.get("tx_velocity", 0)
    if velocity > 5:
        flags.append(("🟡", f"High transaction velocity: {velocity:.1f} transactions/day"))

    # --- Macro correlation ---
    if not monthly_df.empty and "ncua_cc_rate" in monthly_df.columns:
        try:
            corr = monthly_df["tx_count"].corr(monthly_df["ncua_cc_rate"])
            if corr > 0.5:
                flags.append((
                    "🔴",
                    f"Activity highly correlates (r={corr:.2f}) with NCUA credit card rate hikes",
                ))
            elif corr > 0.3:
                flags.append((
                    "🟡",
                    f"Moderate correlation (r={corr:.2f}) between activity and macroeconomic stress",
                ))
            # Look for spike months
            if len(monthly_df) >= 3:
                rate_delta = monthly_df["ncua_cc_rate"].diff()
                tx_delta = monthly_df["tx_count"].diff()
                co_spikes = ((rate_delta > 0.3) & (tx_delta > tx_delta.median())).sum()
                if co_spikes >= 2:
                    flags.append(("🔴", f"Transaction bursts co-occur with interest rate spikes in {co_spikes} periods"))
        except Exception:
            pass

    # --- High risk score ---
    if risk_score >= 0.85:
        flags.append(("🔴", f"LightGBM risk score {risk_score * 100:.0f}/100 — exceeds HIGH RISK threshold"))
    elif risk_score >= 0.70:
        flags.append(("🟡", f"Risk score {risk_score * 100:.0f}/100 — elevated, warrants further review"))

    # --- Out-degree (fan-out smurfing) ---
    out_deg = stat_features.get("out_degree", 0)
    if out_deg > 20:
        flags.append(("🟡", f"High fan-out: funds sent to {int(out_deg)} distinct counterparties (smurfing pattern)"))

    # Fallback
    if not flags:
        flags.append(("🔵", "No significant red flags detected for this account"))

    return [f"{sev} {msg}" for sev, msg in flags]
