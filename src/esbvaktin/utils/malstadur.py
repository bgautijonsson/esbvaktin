"""Centralised wrapper for Miðeind's Málstaður API (api.malstadur.is).

Single canonical entry point for grammar correction and translation calls.
Built-in:
  - 0.5s inter-call delay (translate endpoint rate-limits aggressively)
  - Exponential backoff on 429 / 502 / 503 / 504 (10s, 20s, 40s)
  - Auth via MALSTADUR_API_KEY environment variable
  - httpx.Client lifecycle management (use as context manager)

Pricing reminder (~1 kr per 100 chars for grammar/translate; 2,000 kr/hr
for speech): batch grammar calls (max 10 texts), avoid re-checking text
already processed in the same session.

Usage:
    from esbvaktin.utils.malstadur import MalstadurClient

    with MalstadurClient() as client:
        results = client.check_grammar(["Texti einn", "Texti tveir"])
        translated = client.translate("Hello world", "is")

For one-shot calls without explicit lifecycle management, use the module
helpers `check_grammar()` and `translate()` — each opens a fresh client.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MALSTADUR_BASE = "https://api.malstadur.is/v1"

# Default tuning. Override per-instance via constructor kwargs if needed.
DEFAULT_CALL_DELAY = 0.5  # seconds between calls
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 10.0  # seconds (doubles each retry)
DEFAULT_TIMEOUT = 60.0  # per-request HTTP timeout
DEFAULT_GRAMMAR_BATCH_SIZE = 10  # API caps grammar texts at 10 per call

RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})


class MalstadurError(RuntimeError):
    """Raised when the Málstaður API call fails after retries."""


class MalstadurClient:
    """Synchronous Málstaður API client with retry + rate-limit handling."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        call_delay: float = DEFAULT_CALL_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("MALSTADUR_API_KEY", "")
        if not self._api_key:
            raise MalstadurError(
                "MALSTADUR_API_KEY not set. Get one at https://malstadur.mideind.is/askrift"
            )
        self._call_delay = call_delay
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._client = httpx.Client(timeout=timeout)
        self._last_call_at: float | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    def __enter__(self) -> MalstadurClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    # ── Public API ────────────────────────────────────────────────────

    def check_grammar(
        self,
        texts: list[str],
        *,
        batch_size: int = DEFAULT_GRAMMAR_BATCH_SIZE,
    ) -> list[dict]:
        """Grammar-check texts via /v1/grammar.

        Splits into batches of `batch_size` (the API caps at 10). Returns one
        dict per input text, each containing `originalText`, `changedText`,
        and `diffAnnotations` per the upstream schema.
        """
        if not texts:
            return []

        out: list[dict] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            data = self._post("/grammar", {"texts": batch})
            results = data.get("results", [])
            # The API returns one result per input. If something is dropped,
            # pad with the original so callers can still index by position.
            for i, original in enumerate(batch):
                if i < len(results):
                    out.append(results[i])
                else:
                    out.append(
                        {
                            "originalText": original,
                            "changedText": original,
                            "diffAnnotations": [],
                        }
                    )
        return out

    def correct_grammar(
        self,
        texts: list[str],
        *,
        batch_size: int = DEFAULT_GRAMMAR_BATCH_SIZE,
    ) -> list[str]:
        """Convenience: grammar-check and return only the corrected strings.

        Falls back to the original text when the API returns no `changedText`.
        Useful when callers don't need the per-annotation diff information.
        """
        results = self.check_grammar(texts, batch_size=batch_size)
        out: list[str] = []
        for original, item in zip(texts, results):
            corrected = item.get("changedText") or item.get("originalText")
            out.append(corrected if corrected else original)
        return out

    def translate(self, text: str, target_language: str) -> str:
        """Translate text via /v1/translate. Returns the translated string."""
        if not text:
            return ""
        data = self._post(
            "/translate",
            {"text": text, "targetLanguage": target_language},
        )
        return data.get("text", "")

    # ── Internal helpers ──────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

    def _throttle(self) -> None:
        """Sleep just enough to respect the inter-call delay."""
        if self._last_call_at is None:
            return
        elapsed = time.monotonic() - self._last_call_at
        wait = self._call_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _post(self, path: str, body: dict) -> dict:
        url = f"{MALSTADUR_BASE}{path}"
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                resp = self._client.post(url, headers=self._headers(), json=body)
            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "Málstaður %s transport error (%s); retrying in %.0fs",
                        path,
                        e,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise MalstadurError(f"Málstaður {path} transport error after retries: {e}") from e
            finally:
                self._last_call_at = time.monotonic()

            if resp.status_code in RETRY_STATUS_CODES:
                if attempt < self._max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "Málstaður %s HTTP %d; retrying in %.0fs",
                        path,
                        resp.status_code,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise MalstadurError(
                    f"Málstaður {path} HTTP {resp.status_code} after retries: {resp.text[:200]}"
                )

            if resp.is_success:
                return resp.json()

            raise MalstadurError(f"Málstaður {path} HTTP {resp.status_code}: {resp.text[:200]}")

        raise MalstadurError(f"Málstaður {path}: exhausted retries")  # unreachable


# ── Module-level helpers ──────────────────────────────────────────────


def check_grammar(texts: list[str], **kwargs: Any) -> list[dict]:
    """One-shot grammar check. For repeated calls, prefer MalstadurClient."""
    with MalstadurClient(**kwargs) as client:
        return client.check_grammar(texts)


def translate(text: str, target_language: str, **kwargs: Any) -> str:
    """One-shot translation. For repeated calls, prefer MalstadurClient."""
    with MalstadurClient(**kwargs) as client:
        return client.translate(text, target_language)
