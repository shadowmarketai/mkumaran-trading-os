"""
Predictive Loss Probability Model

Trains a sklearn GradientBoostingClassifier on historical Signal + Outcome
data. Produces P(loss) for new signals so the entry gate can suppress
high-risk trades before they ever reach the user.

Data pipeline:
  features  = Signal.feature_vector (already L2 / fixed-order via signal_features)
  label     = 1 if Outcome.outcome == "LOSS" else 0

Model artifact is pickled to `data/predictor_model.pkl`. A module-level
singleton `_PREDICTOR` lazy-loads it on first call. Retraining is exposed
via `retrain_predictor()` — idempotent, safe to call from a background
loop or n8n.

Fallback behavior: if the model file doesn't exist OR training fails due
to insufficient data, `is_ready()` returns False and the entry gate skips
prediction (no signals are suppressed, no crashes).
"""

from __future__ import annotations

import logging
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from mcp_server.db import SessionLocal
from mcp_server.models import Outcome, Signal
from mcp_server.signal_features import FEATURE_KEYS

logger = logging.getLogger(__name__)


MODEL_DIR = Path(os.getenv("PREDICTOR_MODEL_DIR", "data"))
MODEL_FILE = MODEL_DIR / "predictor_model.pkl"
META_FILE = MODEL_DIR / "predictor_meta.json"

# Minimum samples before training at all
MIN_TRAIN_SAMPLES = int(os.getenv("PREDICTOR_MIN_SAMPLES", "30"))


class SignalPredictor:
    """
    Gradient-boosted binary classifier: P(loss) for a given feature vector.
    """

    def __init__(self) -> None:
        self.model: Any = None
        self.feature_keys: list[str] = list(FEATURE_KEYS)
        self.version: str = "uninitialized"
        self.trained_at: str | None = None
        self.train_samples: int = 0
        self.train_loss_rate: float = 0.0
        self.cv_auc: float | None = None

    # ── Persistence ───────────────────────────────────────────────────

    def save(self) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with MODEL_FILE.open("wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_keys": self.feature_keys,
                "version": self.version,
                "trained_at": self.trained_at,
                "train_samples": self.train_samples,
                "train_loss_rate": self.train_loss_rate,
                "cv_auc": self.cv_auc,
            }, f)
        logger.info("Predictor saved: %s (v=%s, n=%d)", MODEL_FILE, self.version, self.train_samples)

    def load(self) -> bool:
        if not MODEL_FILE.exists():
            return False
        try:
            with MODEL_FILE.open("rb") as f:
                data = pickle.load(f)
            self.model = data.get("model")
            self.feature_keys = data.get("feature_keys") or list(FEATURE_KEYS)
            self.version = data.get("version", "unknown")
            self.trained_at = data.get("trained_at")
            self.train_samples = data.get("train_samples", 0)
            self.train_loss_rate = data.get("train_loss_rate", 0.0)
            self.cv_auc = data.get("cv_auc")
            logger.info(
                "Predictor loaded: v=%s n=%d loss_rate=%.2f",
                self.version, self.train_samples, self.train_loss_rate,
            )
            return self.model is not None
        except Exception as e:
            logger.warning("Predictor load failed: %s", e)
            self.model = None
            return False

    def is_ready(self) -> bool:
        return self.model is not None

    # ── Inference ─────────────────────────────────────────────────────

    def predict(self, feature_vector: list[float]) -> tuple[float, list[str]]:
        """
        Return (p_loss, top_risk_feature_names).

        The top features come from the model's `feature_importances_` *intersected*
        with features that are actually non-zero / non-neutral in the query vector.
        If model is not ready, returns (0.0, []).
        """
        if not self.is_ready() or not feature_vector:
            return 0.0, []

        try:
            vec = np.array([float(x) for x in feature_vector], dtype=np.float32).reshape(1, -1)

            # Pad/truncate to model width
            model_width = getattr(self.model, "n_features_in_", vec.shape[1])
            if vec.shape[1] < model_width:
                padded = np.zeros((1, model_width), dtype=np.float32)
                padded[0, : vec.shape[1]] = vec[0]
                vec = padded
            elif vec.shape[1] > model_width:
                vec = vec[:, :model_width]

            proba = self.model.predict_proba(vec)[0]
            # classes_ might be [0, 1] (win, loss) — grab class=1 column
            classes = list(getattr(self.model, "classes_", [0, 1]))
            if 1 in classes:
                p_loss = float(proba[classes.index(1)])
            else:
                p_loss = float(proba[-1])

            # Top risk features: feature_importances_ weighted by |value|
            top: list[str] = []
            importances = getattr(self.model, "feature_importances_", None)
            if importances is not None and len(importances) == model_width:
                raw = vec[0]
                scores = np.array(importances) * np.abs(raw)
                order = np.argsort(-scores)
                for idx in order:
                    if idx < len(self.feature_keys):
                        name = self.feature_keys[idx]
                        if scores[idx] > 0:
                            top.append(name)
                    if len(top) >= 5:
                        break

            return max(0.0, min(1.0, p_loss)), top
        except Exception as e:
            logger.debug("Predictor.predict failed: %s", e)
            return 0.0, []

    # ── Training ──────────────────────────────────────────────────────

    def train(self) -> dict[str, Any]:
        """
        Pull all (Signal, Outcome) pairs with a non-null feature_vector and
        fit a GradientBoostingClassifier. Returns metrics dict.
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.model_selection import cross_val_score
        except Exception as e:
            return {"status": "error", "reason": f"sklearn unavailable: {e}"}

        session = SessionLocal()
        try:
            rows = (
                session.query(Signal, Outcome)
                .join(Outcome, Outcome.signal_id == Signal.id)
                .filter(Signal.feature_vector.isnot(None))
                .all()
            )
        finally:
            session.close()

        X: list[list[float]] = []
        y: list[int] = []
        for sig, out in rows:
            vec = sig.feature_vector
            if not vec or not isinstance(vec, list):
                continue
            try:
                x = [float(v) for v in vec]
            except Exception:
                continue
            label = 1 if (out.outcome or "").upper() == "LOSS" else 0
            X.append(x)
            y.append(label)

        if len(X) < MIN_TRAIN_SAMPLES:
            return {
                "status": "insufficient_data",
                "samples": len(X),
                "required": MIN_TRAIN_SAMPLES,
            }

        # Pad all rows to same width (append-only FEATURE_KEYS evolution)
        max_w = max(len(row) for row in X)
        X_mat = np.zeros((len(X), max_w), dtype=np.float32)
        for i, row in enumerate(X):
            X_mat[i, : len(row)] = row
        y_arr = np.array(y, dtype=np.int32)

        loss_rate = float(y_arr.mean())
        # Guard: need both classes
        if len(set(y)) < 2:
            return {
                "status": "insufficient_diversity",
                "samples": len(X),
                "loss_rate": loss_rate,
                "reason": "only one class present",
            }

        model = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )

        try:
            model.fit(X_mat, y_arr)
        except Exception as e:
            return {"status": "error", "reason": f"fit failed: {e}"}

        # Cross-val AUC if we have enough samples
        cv_auc = None
        try:
            if len(X) >= 50:
                scores = cross_val_score(model, X_mat, y_arr, cv=min(5, len(X) // 10), scoring="roc_auc")
                cv_auc = float(scores.mean())
        except Exception as e:
            logger.debug("CV AUC skipped: %s", e)

        self.model = model
        self.version = datetime.utcnow().strftime("v%Y%m%d_%H%M%S")
        self.trained_at = datetime.utcnow().isoformat()
        self.train_samples = len(X)
        self.train_loss_rate = loss_rate
        self.cv_auc = cv_auc
        self.feature_keys = list(FEATURE_KEYS)

        self.save()

        return {
            "status": "ok",
            "version": self.version,
            "samples": len(X),
            "loss_rate": round(loss_rate, 3),
            "cv_auc": round(cv_auc, 3) if cv_auc is not None else None,
            "feature_width": int(max_w),
        }

    def meta(self) -> dict[str, Any]:
        return {
            "ready": self.is_ready(),
            "version": self.version,
            "trained_at": self.trained_at,
            "train_samples": self.train_samples,
            "train_loss_rate": round(self.train_loss_rate, 3),
            "cv_auc": round(self.cv_auc, 3) if self.cv_auc is not None else None,
            "feature_width": len(self.feature_keys),
        }


# ── Module singleton ──────────────────────────────────────────────────────

_PREDICTOR: SignalPredictor | None = None


def get_predictor() -> SignalPredictor:
    """Return the singleton predictor, loading it from disk on first call."""
    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = SignalPredictor()
        _PREDICTOR.load()
    return _PREDICTOR


def retrain_predictor() -> dict[str, Any]:
    """Force a full retrain and reload the singleton."""
    global _PREDICTOR
    p = SignalPredictor()
    result = p.train()
    if result.get("status") == "ok":
        _PREDICTOR = p
    return result
