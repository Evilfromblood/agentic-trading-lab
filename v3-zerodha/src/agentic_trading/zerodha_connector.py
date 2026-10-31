"""Read-only Kite Connect bridge. No order placement methods are exposed."""
from __future__ import annotations
import os
from typing import Any
import keyring
from kiteconnect import KiteConnect

SERVICE_NAME = "agentic-trading-lab-kite"
TOKEN_ACCOUNT = "access_token"

class KiteConfigurationError(RuntimeError):
    pass

class ZerodhaReadOnlyConnector:
    def __init__(self) -> None:
        api_key = os.getenv("KITE_API_KEY", "").strip()
        if not api_key:
            raise KiteConfigurationError("Set KITE_API_KEY in your .env file first.")
        self.client = KiteConnect(api_key=api_key)
        token = keyring.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
        if token:
            self.client.set_access_token(token)

    @staticmethod
    def login_url() -> str:
        api_key = os.getenv("KITE_API_KEY", "").strip()
        if not api_key:
            raise KiteConfigurationError("Set KITE_API_KEY in your .env file first.")
        return KiteConnect(api_key=api_key).login_url()

    def complete_login(self, request_token: str) -> dict[str, Any]:
        secret = os.getenv("KITE_API_SECRET", "").strip()
        if not secret:
            raise KiteConfigurationError("Set KITE_API_SECRET in your .env file first.")
        session = self.client.generate_session(request_token, api_secret=secret)
        token = session["access_token"]
        keyring.set_password(SERVICE_NAME, TOKEN_ACCOUNT, token)
        self.client.set_access_token(token)
        return {k: session.get(k) for k in ("user_id", "user_name", "email", "login_time")}

    def _require_session(self) -> None:
        if not keyring.get_password(SERVICE_NAME, TOKEN_ACCOUNT):
            raise KiteConfigurationError("Not authenticated. Open /login and complete Kite login.")

    def profile(self) -> dict[str, Any]:
        self._require_session(); return self.client.profile()
    def holdings(self) -> list[dict[str, Any]]:
        self._require_session(); return self.client.holdings()
    def positions(self) -> dict[str, Any]:
        self._require_session(); return self.client.positions()
    def margins(self) -> dict[str, Any]:
        self._require_session(); return self.client.margins()

    def logout(self) -> None:
        token = keyring.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
        if token:
            self.client.set_access_token(token)
            self.client.invalidate_access_token(token)
        try:
            keyring.delete_password(SERVICE_NAME, TOKEN_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass
