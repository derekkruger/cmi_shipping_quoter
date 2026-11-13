"""Shared plumbing for carrier API clients (OAuth token caching, HTTP errors)."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

import requests

from ..models import QuoteError, QuoteRequest, Rate

TIMEOUT = 30  # seconds


class CarrierError(QuoteError):
    """A carrier API call failed; message is safe to show to the clerk."""


class Carrier(ABC):
    name: str = ""  # short id, e.g. "ups"
    display_name: str = ""
    required_fields: tuple[str, ...] = ("client_id", "client_secret", "account_number")

    # Token cache is shared per class and keyed by credentials, so changing
    # credentials in the settings page automatically fetches a fresh token.
    _token_cache: dict[tuple, tuple[str, float]] = {}
    _token_lock = threading.Lock()

    def __init__(self, config: dict, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()

    # ----- configuration -------------------------------------------------
    @property
    def production(self) -> bool:
        return self.config.get("environment") == "production"

    def missing_fields(self) -> list[str]:
        return [f for f in self.required_fields if not str(self.config.get(f, "")).strip()]

    def ensure_configured(self) -> None:
        missing = self.missing_fields()
        if missing:
            raise CarrierError(
                f"{self.display_name} is missing: {', '.join(missing)}. Add it on the Settings page."
            )

    # ----- auth ---------------------------------------------------------
    def get_token(self) -> str:
        self.ensure_configured()
        key = (self.name, self.production, self.config["client_id"], self.config["client_secret"],
               self.config.get("account_number", ""))
        with self._token_lock:
            cached = self._token_cache.get(key)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
        token, expires_in = self._fetch_token()
        with self._token_lock:
            self._token_cache[key] = (token, time.time() + max(int(expires_in), 120))
        return token

    @abstractmethod
    def _fetch_token(self) -> tuple[str, int]:
        """Return (access_token, expires_in_seconds)."""

    def test_connection(self) -> str:
        self.get_token()
        env = "production" if self.production else "sandbox"
        return f"Connected to {self.display_name} ({env}). Credentials accepted."

    # ----- rating -------------------------------------------------------
    @abstractmethod
    def get_rates(self, req: QuoteRequest) -> list[Rate]:
        ...

    # ----- helpers ------------------------------------------------------
    def _post(self, url: str, **kwargs) -> dict:
        try:
            resp = self.session.post(url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise CarrierError(f"{self.display_name}: could not reach the API ({exc.__class__.__name__}).") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            raise CarrierError(f"{self.display_name}: {self._error_message(body) or f'HTTP {resp.status_code}'}")
        return body

    def _error_message(self, body: dict) -> str:
        return ""
