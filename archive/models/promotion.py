"""
Champion / challenger model promotion (RETRAIN-01/02).

Generic and dependency-light (no xgboost import), so it is unit-testable with
stub models. A challenger is trained on the older `fit` slice only, then BOTH the
live champion and the challenger are scored on a held-out `holdout` slice (the most
recent `holdout_days`) the challenger never saw. The challenger is promoted —
atomically swapped into the live model file and reloaded — only if it beats the
champion out-of-sample. Otherwise the champion is kept.

`live_model` / `make_challenger()` are duck-typed: they expose
  .is_trained, .evaluate(df)->float|None, .train(df)->dict, .model_path,
  .save_model(), .load_model()
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

from loguru import logger

from models.validation import time_holdout_split


def champion_challenger(
    name: str,
    live_model: Any,
    make_challenger: Callable[[], Any],
    df,
    holdout_days: int,
    margin: float = 0.0,
) -> Dict[str, Any]:
    start_time = datetime.now()
    fit_df, holdout_df = time_holdout_split(df, holdout_days)
    # If a genuine out-of-sample holdout can't be formed, DO NOT degrade to an
    # in-sample (df, df) comparison — that silently disables the safety gate and an
    # overfit challenger would always "win" and get promoted (RETRAIN-02). Keep the
    # live champion untouched and report why.
    if len(fit_df) == 0 or len(holdout_df) == 0:
        logger.warning(f"{name}: data span ≤ holdout_days ({holdout_days}) — "
                       f"cannot form an out-of-sample holdout; keeping champion")
        return {"model": name, "promoted": False, "old_auc": None, "new_auc": None,
                "holdout_auc": None, "auc_change": None,
                "reason": "insufficient holdout window — champion kept",
                "training_time_seconds": (datetime.now() - start_time).total_seconds(),
                "timestamp": datetime.now().isoformat()}

    champion_auc = live_model.evaluate(holdout_df) if getattr(live_model, "is_trained", False) else None

    challenger = make_challenger()
    try:
        metrics = challenger.train(fit_df) or {}
    except Exception as e:
        logger.warning(f"{name}: challenger training failed: {e}")
        return {"model": name, "promoted": False, "old_auc": champion_auc, "new_auc": None,
                "holdout_auc": None, "auc_change": None, "note": f"train failed: {e}",
                "training_time_seconds": (datetime.now() - start_time).total_seconds(),
                "timestamp": datetime.now().isoformat()}

    challenger_auc = challenger.evaluate(holdout_df)

    if challenger_auc is None:
        promote = not getattr(live_model, "is_trained", False)
        reason = "no champion yet → promote" if promote else "challenger AUC unmeasurable → keep champion"
    elif champion_auc is None:
        promote, reason = True, "no champion AUC → promote challenger"
    else:
        promote = challenger_auc >= champion_auc + margin
        reason = "challenger ≥ champion → promote" if promote else "challenger worse → keep champion"

    if promote:
        # The holdout already served its accept/reject purpose. Now refit the
        # challenger on the FULL df (fit + holdout) so the SHIPPED model has seen the
        # most recent bars — otherwise every promotion ships a model permanently
        # starved of the freshest (most predictive) data (RETRAIN refit). This final
        # fit is intentionally not re-validated; the gate already passed.
        try:
            challenger.train(df)
        except Exception as e:
            logger.warning(f"{name}: full-data refit failed ({e}) — shipping the gated fit instead")
        challenger.model_path = live_model.model_path
        challenger.save_model()      # atomic write to the live model file
        live_model.load_model()      # refresh the in-memory singleton
    # clean up the challenger's temp file if it was separate
    try:
        cp = Path(challenger.model_path)
        if cp != Path(live_model.model_path) and cp.exists():
            cp.unlink()
    except Exception:
        pass

    auc_change = (challenger_auc - champion_auc) if (challenger_auc is not None and champion_auc is not None) else None
    logger.info(f"{name}: champion={champion_auc} challenger(holdout)={challenger_auc} "
                f"→ {'PROMOTED' if promote else 'KEPT CHAMPION'} ({reason})")
    return {
        "model": name,
        "old_auc": champion_auc,
        "new_auc": metrics.get("auc"),
        "holdout_auc": challenger_auc,
        "auc_change": auc_change,
        "promoted": promote,
        "reason": reason,
        "training_samples": metrics.get("train_samples"),
        "training_time_seconds": (datetime.now() - start_time).total_seconds(),
        "timestamp": datetime.now().isoformat(),
    }
