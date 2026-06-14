"""Model-agnostic prediction for sklearn, LightGBM sklearn API, and LightGBM Booster."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

_LOG = logging.getLogger(__name__)


def _module_name(obj: Any) -> str:
    return type(obj).__module__ or ""


def _is_lightgbm_booster(obj: Any) -> bool:
    return type(obj).__name__ == "Booster" and "lightgbm" in _module_name(obj).lower()


def _is_lightgbm_sklearn(obj: Any) -> bool:
    mn = _module_name(obj).lower()
    return "lightgbm.sklearn" in mn or mn.endswith("lightgbm.sklearn")


def predict_breach_probability(model: Any, features_2d: np.ndarray) -> float:
    """
    Return a breach probability-like score in [0, 1].
    Handles LightGBM Booster, LGBMClassifier/LGBMRegressor, sklearn classifiers, regressors.
    """
    X = np.asarray(features_2d, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    try:
        val: float
        if hasattr(model, "predict_proba") and not _is_lightgbm_booster(model):
            proba = model.predict_proba(X)
            arr = np.asarray(proba, dtype=np.float64).ravel()
            if arr.size >= 2:
                val = float(arr[-1])
            else:
                val = float(arr[0])
        elif _is_lightgbm_booster(model):
            raw = model.predict(X)
            raw_f = float(np.asarray(raw, dtype=np.float64).ravel()[0])
            if 0.0 <= raw_f <= 1.0:
                val = raw_f
            else:
                val = float(1.0 / (1.0 + np.exp(-np.clip(raw_f, -30.0, 30.0))))
        else:
            raw = model.predict(X)
            raw_f = float(np.asarray(raw, dtype=np.float64).ravel()[0])
            if 0.0 <= raw_f <= 1.0:
                val = raw_f
            else:
                val = float(1.0 / (1.0 + np.exp(-np.clip(raw_f, -30.0, 30.0))))

        val = float(np.clip(val, 0.0, 1.0))
        if _LOG.isEnabledFor(logging.DEBUG):
            _LOG.debug(
                "breach_prob model=%s raw_clipped=%.4f",
                type(model).__name__,
                val,
            )
        return val
    except Exception as e:
        _LOG.warning("breach probability prediction failed (%s): %s", type(model).__name__, e)
        return 0.0


def predict_time_to_breach(model: Any, features_2d: np.ndarray, default: float = 9999.0) -> float:
    """Regression scalar; always non-negative."""
    X = np.asarray(features_2d, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    try:
        raw = model.predict(X)
        v = float(np.asarray(raw, dtype=np.float64).ravel()[0])
        if np.isnan(v) or np.isinf(v):
            return default
        return max(0.0, v)
    except Exception as e:
        _LOG.warning("time-to-breach prediction failed (%s): %s", type(model).__name__, e)
        return default
