"""A deliberately limited, read-only facade for Kite Connect.

This facade prevents application code from issuing write requests through the
connector. It is not a security sandbox for hostile Python in this process:
use a broker credential without trading permission and egress policy for that boundary.
"""
from __future__ import annotations

import os
import types
from typing import Any, Callable

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore[assignment]

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None  # type: ignore[assignment]

try:
    from requests.adapters import HTTPAdapter
    from requests import PreparedRequest, Response
except ImportError:
    HTTPAdapter = object  # type: ignore[assignment,misc]
    PreparedRequest = Any  # type: ignore[assignment,misc]
    Response = Any  # type: ignore[assignment,misc]

SERVICE_NAME = "agentic-trading-lab-kite"
TOKEN_ACCOUNT = "access_token"

_READ_ONLY_ALLOWLIST = frozenset(
    {
        "quote",
        "ohlc",
        "ltp",
        "historical_data",
        "instruments",
        "profile",
        "margins",
        "holdings",
        "positions",
        "trades",
        "orders",
        "order_history",
        "order_trades",
        "mf_orders",
        "mf_sips",
        "mf_instruments",
        "mf_holdings",
        "get_gtts",
        "get_gtt",
        "login_url",
        "basket_order_margins",
        "order_margins",
        "get_virtual_contract_note",
        "get_auction_instruments",
        "trigger_range",
    }
)
_BLOCKED_METHODS = frozenset(
    {
        "place_order",
        "modify_order",
        "cancel_order",
        "exit_order",
        "place_autoslice_order",
        "place_gtt",
        "modify_gtt",
        "delete_gtt",
        "convert_position",
        "place_mf_order",
        "cancel_mf_order",
        "place_mf_sip",
        "modify_mf_sip",
        "cancel_mf_sip",
        "generate_session",
        "renew_access_token",
        "invalidate_access_token",
        "invalidate_refresh_token",
        "set_access_token",
        "set_session_expiry_hook",
        "_post",
        "_put",
        "_delete",
        "_request",
    }
)


class KiteConfigurationError(RuntimeError):
    pass


def _blocked(name: str) -> PermissionError:
    return PermissionError(f"Kite operation '{name}' is forbidden in read-only mode")


def _safe_get_stored_token() -> str | None:
    """Best-effort local token retrieval; unavailable keyrings never break reads."""
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except Exception:
        return None


def _safe_set_stored_token(token: str) -> None:
    """Best-effort local token storage; errors are silently ignored."""
    if keyring is None:
        return
    try:
        keyring.set_password(SERVICE_NAME, TOKEN_ACCOUNT, token)
    except Exception:
        pass


def _safe_delete_stored_token() -> None:
    """Best-effort local token deletion; errors are silently ignored."""
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except Exception:
        pass


def _keyring_call(operation: str, *args: str) -> Any | None:
    if operation == "get_password":
        return _safe_get_stored_token()
    if operation == "set_password":
        _safe_set_stored_token(args[1] if len(args) > 1 else "")
        return None
    if operation == "delete_password":
        _safe_delete_stored_token()
        return None
    return None


class ReadOnlyTransportAdapter(HTTPAdapter):
    """Transport adapter that intercepts and blocks non-GET HTTP requests at the transport level."""

    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> Response:
        if request.method != "GET":
            raise PermissionError(
                f"Blocked non-GET request: HTTP {request.method} is forbidden in read-only mode"
            )
        return super().send(request, *args, **kwargs)


if KiteConnect is not None:
    class ReadOnlyKiteConnect(KiteConnect):  # type: ignore[misc]
        """KiteConnect subclass enforcing read-only behavior at method and transport layers."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            adapter = ReadOnlyTransportAdapter()
            self.reqsession.mount("https://", adapter)
            self.reqsession.mount("http://", adapter)

        def _request(self, method: str, *args: Any, **kwargs: Any) -> Any:
            if method.upper() != "GET":
                raise PermissionError(f"HTTP method '{method}' is forbidden in read-only mode")
            return super()._request(method, *args, **kwargs)

        def _post(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("HTTP POST is forbidden in read-only mode")

        def _put(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("HTTP PUT is forbidden in read-only mode")

        def _delete(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("HTTP DELETE is forbidden in read-only mode")

        def place_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("place_order")

        def modify_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("modify_order")

        def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("cancel_order")

        def exit_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("exit_order")

        def place_autoslice_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("place_autoslice_order")

        def place_gtt(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("place_gtt")

        def modify_gtt(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("modify_gtt")

        def delete_gtt(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("delete_gtt")

        def convert_position(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("convert_position")

        def place_mf_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("place_mf_order")

        def cancel_mf_order(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("cancel_mf_order")

        def place_mf_sip(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("place_mf_sip")

        def modify_mf_sip(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("modify_mf_sip")

        def cancel_mf_sip(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("cancel_mf_sip")

        def generate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("generate_session")

        def renew_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("renew_access_token")

        def invalidate_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("invalidate_access_token")

        def invalidate_refresh_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("invalidate_refresh_token")
else:
    class ReadOnlyKiteConnect:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise KiteConfigurationError("kiteconnect library is required")


class _ReadOnlyKiteWrapper:
    """Explicit API facade; it never changes the caller-provided client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name in _BLOCKED_METHODS:
            raise _blocked(name)
        if name not in _READ_ONLY_ALLOWLIST:
            raise PermissionError(f"Kite operation '{name}' is not in the read-only allowlist")
        if not hasattr(self._client, name):
            raise AttributeError(f"Underlying client has no attribute '{name}'")
        attr = getattr(self._client, name)
        if callable(attr):
            def bound_call(this: Any, *args: Any, **kwargs: Any) -> Any:
                return getattr(this._client, name)(*args, **kwargs)

            bound_call.__name__ = name
            return types.MethodType(bound_call, self)
        return attr

    def _request(self, method: str, *_args: Any, **_kwargs: Any) -> None:
        """Request-level stop for direct lower-level transport access."""
        raise _blocked(f"_request:{method}")


class ZerodhaReadOnlyConnector:
    """Read-only Kite connector with no mutation of injected client objects."""

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        injected = client is not None
        if client is None:
            key = api_key or os.getenv("KITE_API_KEY", "").strip()
            if not key:
                raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
            if KiteConnect is None:
                raise KiteConfigurationError("kiteconnect library is required")
            client = ReadOnlyKiteConnect(api_key=key)
        self._client = client
        token = _safe_get_stored_token()
        if token and not injected:
            try:
                client.set_access_token(token)
            except Exception:
                pass

    @property
    def client(self) -> _ReadOnlyKiteWrapper:
        return _ReadOnlyKiteWrapper(self._client)

    @staticmethod
    def login_url(api_key: str | None = None) -> str:
        key = api_key or os.getenv("KITE_API_KEY", "").strip()
        if not key:
            raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
        if KiteConnect is None:
            raise KiteConfigurationError("kiteconnect library is required")
        return KiteConnect(api_key=key).login_url()

    def _require_session(self) -> None:
        if not _safe_get_stored_token():
            raise KiteConfigurationError("Not authenticated. Configure a read-only Kite access token.")

    def profile(self) -> dict[str, Any]:
        self._require_session()
        return self.client.profile()

    def holdings(self) -> list[dict[str, Any]]:
        self._require_session()
        return self.client.holdings()

    def positions(self) -> dict[str, Any]:
        self._require_session()
        return self.client.positions()

    def margins(self) -> dict[str, Any]:
        self._require_session()
        return self.client.margins()

    def logout(self) -> None:
        _safe_delete_stored_token()

    def __getattr__(self, name: str) -> Any:
        if name in _BLOCKED_METHODS:
            raise _blocked(name)
        if name not in _READ_ONLY_ALLOWLIST:
            raise AttributeError(name)
        return getattr(self.client, name)
