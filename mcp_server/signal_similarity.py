"""
Signal Similarity Search — find historical signals similar to a query signal.

Uses numpy cosine similarity on the `feature_vector` column. No pgvector
required — we just materialize the last N signals into an in-memory matrix
and dot-product against the query vector.

A module-level cache (TTL 5 minutes) keeps the matrix hot so we don't
re-query the DB on every postmortem.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from mcp_server.models import Outcome, Signal
from mcp_server.signal_features import normalize_vector

logger = logging.getLogger(__name__)


# Module cache: (timestamp, ids, matrix, meta)
_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "ids": [],
    "matrix": None,  # np.ndarray (N, D)
    "meta": [],      # list of dicts matching each row
}
_CACHE_TTL = 300  # 5 min
_MAX_SIGNALS = 2000


def _build_cache(session: Session) -> None:
    """Load the last N signals with a non-null feature_vector into memory."""
    rows = (
        session.query(Signal, Outcome)
        .outerjoin(Outcome, Outcome.signal_id == Signal.id)
        .filter(Signal.feature_vector.isnot(None))
        .order_by(Signal.id.desc())
        .limit(_MAX_SIGNALS)
        .all()
    )

    ids: list[int] = []
    vectors: list[np.ndarray] = []
    meta: list[dict[str, Any]] = []

    for sig, out in rows:
        vec = sig.feature_vector
        if not vec or not isinstance(vec, list):
            continue
        try:
            arr = normalize_vector([float(x) for x in vec])
        except Exception:
            continue
        if arr.size == 0:
            continue

        ids.append(sig.id)
        vectors.append(arr)
        meta.append({
            "id": sig.id,
            "ticker": sig.ticker,
            "direction": sig.direction,
            "signal_date": sig.signal_date.isoformat() if sig.signal_date else None,
            "entry_price": float(sig.entry_price or 0),
            "stop_loss": float(sig.stop_loss or 0),
            "target": float(sig.target or 0),
            "regime": sig.entry_regime,
            "rsi": float(sig.entry_rsi or 0) if sig.entry_rsi is not None else None,
            "adx": float(sig.entry_adx or 0) if sig.entry_adx is not None else None,
            "status": sig.status,
            "outcome": out.outcome if out else None,
            "pnl_amount": float(out.pnl_amount or 0) if out else None,
            "exit_reason": out.exit_reason if out else None,
        })

    if not vectors:
        _CACHE["matrix"] = None
        _CACHE["ids"] = []
        _CACHE["meta"] = []
    else:
        # Pad to max width to tolerate vector-length drift across versions
        max_len = max(v.size for v in vectors)
        padded = np.zeros((len(vectors), max_len), dtype=np.float32)
        for i, v in enumerate(vectors):
            padded[i, : v.size] = v
        _CACHE["matrix"] = padded
        _CACHE["ids"] = ids
        _CACHE["meta"] = meta

    _CACHE["ts"] = time.time()
    logger.debug("Similarity cache rebuilt: %d vectors", len(vectors))


def _ensure_cache(session: Session, force: bool = False) -> None:
    if force or (time.time() - float(_CACHE["ts"]) > _CACHE_TTL) or _CACHE["matrix"] is None:
        _build_cache(session)


def invalidate_cache() -> None:
    """Force next call to rebuild. Call when new signals are added/closed."""
    _CACHE["ts"] = 0.0


def find_similar_signals(
    query_signal: Signal,
    session: Session,
    top_k: int = 5,
    exclude_id: int | None = None,
    only_closed: bool = True,
) -> list[dict[str, Any]]:
    """
    Return the top-K most similar historical signals by cosine similarity
    on the feature vector.

    Args:
        query_signal: Signal ORM instance (must have feature_vector populated)
        session: active DB session
        top_k: number of neighbors to return
        exclude_id: don't return this signal id (usually the query itself)
        only_closed: restrict to signals that have an outcome (useful for RCA)
    """
    if not query_signal.feature_vector:
        return []

    try:
        _ensure_cache(session)
    except Exception as e:
        logger.debug("Similarity cache build failed: %s", e)
        return []

    matrix = _CACHE.get("matrix")
    meta = _CACHE.get("meta") or []
    if matrix is None or len(meta) == 0:
        return []

    try:
        query = normalize_vector([float(x) for x in query_signal.feature_vector])
    except Exception:
        return []

    # Pad/truncate query to match matrix width
    width = matrix.shape[1]
    if query.size < width:
        padded = np.zeros(width, dtype=np.float32)
        padded[: query.size] = query
        query = padded
    elif query.size > width:
        query = query[:width]

    # Cosine similarity (both already L2-normalized)
    sims = matrix @ query  # shape (N,)

    # Rank
    order = np.argsort(-sims)
    results: list[dict[str, Any]] = []
    for idx in order:
        row = meta[int(idx)]
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if only_closed and not row.get("outcome"):
            continue
        results.append({
            **row,
            "similarity": round(float(sims[int(idx)]), 4),
        })
        if len(results) >= top_k:
            break

    return results


def similarity_stats(session: Session) -> dict[str, Any]:
    """Expose cache state for monitoring / debugging."""
    _ensure_cache(session)
    matrix = _CACHE.get("matrix")
    return {
        "cached_vectors": 0 if matrix is None else int(matrix.shape[0]),
        "vector_dim": 0 if matrix is None else int(matrix.shape[1]),
        "cache_age_seconds": round(time.time() - float(_CACHE["ts"]), 1),
        "cache_ttl_seconds": _CACHE_TTL,
    }
