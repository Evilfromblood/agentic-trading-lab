"""A deliberately limited, read-only facade for Kite Connect.

This facade prevents application code from issuing write requests through the
connector. It is not a security sandbox for hostile Python in this process:
use a broker credential without trading permission and egress policy for that boundary.
"""
from __future__ import annotations

import os
import sys
import types
from typing import Any

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore[assignment]

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None  # type: ignore[assignment]

try:
    from requests import PreparedRequest, Response
    from requests.adapters import HTTPAdapter
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
        "generate_session",
        "set_access_token",
        "invalidate_access_token",
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
        "renew_access_token",
        "invalidate_refresh_token",
        "set_session_expiry_hook",
        "_post",
        "_put",
        "_delete",
        "_request",
    }
)

_OPERATION_MESSAGES = {
    "place_order": "Order placement is forbidden in paper-only mode",
    "modify_order": "Order modification is forbidden in paper-only mode",
    "cancel_order": "Order cancellation is forbidden in paper-only mode",
    "exit_order": "Order exit is forbidden in paper-only mode",
    "place_autoslice_order": "Order placement is forbidden in paper-only mode",
    "place_gtt": "GTT placement is forbidden in paper-only mode",
    "modify_gtt": "GTT modification is forbidden in paper-only mode",
    "delete_gtt": "GTT deletion is forbidden in paper-only mode",
    "convert_position": "Position conversion is forbidden in paper-only mode",
    "place_mf_order": "Mutual fund order placement is forbidden in paper-only mode",
    "cancel_mf_order": "Mutual fund order cancellation is forbidden in paper-only mode",
    "place_mf_sip": "Mutual fund SIP placement is forbidden in paper-only mode",
    "modify_mf_sip": "Mutual fund SIP modification is forbidden in paper-only mode",
    "cancel_mf_sip": "Mutual fund SIP cancellation is forbidden in paper-only mode",
}


class KiteConfigurationError(RuntimeError):
    pass


def _blocked(name: str) -> PermissionError:
    prefix = _OPERATION_MESSAGES.get(name, f"Kite operation '{name}' is forbidden")
    return PermissionError(f"{prefix}; Kite operation '{name}' is forbidden in read-only mode")


def _safe_get_stored_token() -> str | None:
    """Best-effort local token retrieval; unavailable keyrings never break reads."""
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return None
    try:
        return mod.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except Exception:  # noqa: BLE001
        return None


def _safe_set_stored_token(token: str) -> None:
    """Best-effort local token storage; errors are silently ignored."""
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return
    try:
        mod.set_password(SERVICE_NAME, TOKEN_ACCOUNT, token)
    except Exception:  # noqa: BLE001
        pass


def _safe_delete_stored_token() -> None:
    """Best-effort local token deletion; errors are silently ignored."""
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return
    try:
        mod.delete_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except Exception:  # noqa: BLE001
        pass


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

    __slots__ = ("_target", "__weakref__")

    def __init__(self, client: Any) -> None:
        self._target = client

    def __getattr__(self, name: str) -> Any:
        if name in _BLOCKED_METHODS:
            raise _blocked(name)
        if name not in _READ_ONLY_ALLOWLIST:
            raise PermissionError(f"Kite operation '{name}' is not in the read-only allowlist")

        def bound_call(this: Any, *args: Any, **kwargs: Any) -> Any:
            target_method = getattr(this._target, name, None)
            if target_method is None:
                raise AttributeError(f"Underlying client has no attribute '{name}'")
            return target_method(*args, **kwargs)

        bound_call.__name__ = name
        return types.MethodType(bound_call, self)

    def generate_session(self, *args: Any, **kwargs: Any) -> Any:
        if not args and not kwargs:
            raise _blocked("generate_session")
        target_fn = getattr(self._target, "generate_session", None)
        if target_fn is None:
            raise AttributeError("Underlying client has no attribute 'generate_session'")
        return target_fn(*args, **kwargs)

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

    def _post(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_post")

    def _put(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_put")

    def _delete(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_delete")

    def _request(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_request")


class ZerodhaReadOnlyConnector:
    """Read-only Kite connector with no mutation of injected client objects."""

    __slots__ = ("_target", "__weakref__")

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        injected = client is not None
        if client is None:
            key = api_key or os.getenv("KITE_API_KEY", "").strip()
            if not key:
                raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
            if KiteConnect is None:
                raise KiteConfigurationError("kiteconnect library is required")
            client = ReadOnlyKiteConnect(api_key=key)
        self._target = client
        token = _safe_get_stored_token()
        if token and not injected:
            try:
                client.set_access_token(token)
            except (AttributeError, RuntimeError, OSError, ValueError, KeyError):
                pass

    @property
    def client(self) -> _ReadOnlyKiteWrapper:
        return _ReadOnlyKiteWrapper(self._target)

    @staticmethod
    def login_url(api_key: str | None = None) -> str:
        key = api_key or os.getenv("KITE_API_KEY", "").strip()
        if not key:
            raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
        if KiteConnect is None:
            raise KiteConfigurationError("kiteconnect library is required")
        return KiteConnect(api_key=key).login_url()

    def complete_login(self, request_token: str) -> dict[str, Any]:
        secret = os.getenv("KITE_API_SECRET", "").strip()
        if not secret:
            raise KiteConfigurationError("Set KITE_API_SECRET in your environment first.")
        session = self._target.generate_session(request_token, api_secret=secret)
        token = session.get("access_token")
        if token:
            _safe_set_stored_token(token)
            if hasattr(self._target, "set_access_token"):
                try:
                    self._target.set_access_token(token)
                except (AttributeError, RuntimeError, OSError, ValueError, KeyError):
                    pass
        return {k: session.get(k) for k in ("user_id", "user_name", "email", "login_time")}

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

    def _post(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_post")

    def _put(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_put")

    def _delete(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_delete")

    def _request(self, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("_request")
