"""Groq LLM construction and resilient invoke with model fallbacks."""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Iterable

from langchain_groq import ChatGroq

from core.sage_config import DEBUG, GROQ_FALLBACK_MODELS, GROQ_MODEL

_LOG = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _cached_llm(model: str, max_tokens: int) -> ChatGroq:
    # Keep constructor minimal for compatibility across langchain-groq versions.
    return ChatGroq(model=model, temperature=0, max_tokens=max_tokens)


def invoke_groq(prompt: str, *, max_tokens: int, models: Iterable[str] | None = None) -> str:
    """
    Invoke Groq with primary + fallback models. Raises last error if all fail.
    """
    chain = list(models) if models is not None else [GROQ_MODEL, *GROQ_FALLBACK_MODELS]
    seen: set[str] = set()
    ordered: list[str] = []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)

    last_err: Exception | None = None
    for model in ordered:
        try:
            llm = _cached_llm(model, max_tokens)
            out = llm.invoke(prompt)
            text = (out.content or "").strip()
            if text:
                if model != GROQ_MODEL:
                    _LOG.info("Groq response used fallback model %s", model)
                return text
        except Exception as e:
            last_err = e
            _LOG.warning("Groq model %s failed: %s", model, e)
            if DEBUG:
                _LOG.exception("Groq detail for model %s", model)
            time.sleep(0.5)
    if last_err:
        raise last_err
    raise RuntimeError("No Groq models configured")
