"""A deliberately limited, read-only facade for Kite Connect.

This facade prevents application code from issuing write requests through the
connector. It is not a security sandbox for hostile Python in this process:
use a broker credential without trading permission and egress policy for that boundary.
"""
from __future__ import annotations

import os
import sys
import types
import weakref
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
        "login_url",
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
        "order_margins",
        "basket_order_margins",
        "get_virtual_contract_note",
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
    "generate_session": "Session generation is forbidden in read-only mode",
    "renew_access_token": "Token renewal is forbidden in read-only mode",
    "invalidate_access_token": "Token invalidation is forbidden in read-only mode",
    "invalidate_refresh_token": "Token invalidation is forbidden in read-only mode",
    "set_access_token": "Token mutation is forbidden in read-only mode",
    "order_margins": "Order margins calculation requires POST and is forbidden in read-only mode",
    "basket_order_margins": "Basket order margins calculation requires POST and is forbidden in read-only mode",
    "get_virtual_contract_note": "Virtual contract note requires POST and is forbidden in read-only mode",
}


class KiteConfigurationError(RuntimeError):
    pass


def _blocked(name: str) -> PermissionError:
    prefix = _OPERATION_MESSAGES.get(name, f"Kite operation '{name}' is forbidden")
    return PermissionError(f"{prefix}; Kite operation '{name}' is forbidden in read-only mode")


def _safe_get_stored_token(raise_on_error: bool = False) -> str | None:
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return None
    try:
        return mod.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        if raise_on_error:
            raise KiteConfigurationError(f"Keyring access failed: {exc}") from exc
        return None


def _safe_set_stored_token(token: str) -> None:
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return
    try:
        mod.set_password(SERVICE_NAME, TOKEN_ACCOUNT, token)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:  # noqa: BLE001
        pass


def _safe_delete_stored_token() -> None:
    mod = sys.modules.get("keyring", keyring)
    if mod is None:
        return
    try:
        mod.delete_password(SERVICE_NAME, TOKEN_ACCOUNT)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:  # noqa: BLE001
        pass


def store_access_token(token: str) -> None:
    _safe_set_stored_token(token)


class ReadOnlyTransportAdapter(HTTPAdapter):
    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> Response:
        if request.method != "GET":
            raise PermissionError(
                f"Blocked non-GET request: HTTP {request.method} is forbidden in read-only mode"
            )
        return super().send(request, *args, **kwargs)


if KiteConnect is not None:
    class ReadOnlyKiteConnect(KiteConnect):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            adapter = ReadOnlyTransportAdapter()
            self.reqsession.mount("https://", adapter)
            self.reqsession.mount("http://", adapter)

        def _request(
            self,
            route: str,
            method: str,
            url_args: Any = None,
            params: Any = None,
            is_json: bool = False,
            query_params: Any = None,
        ) -> Any:
            if method.upper() != "GET":
                raise PermissionError(f"HTTP method '{method}' is forbidden in read-only mode")
            return super()._request(
                route,
                method,
                url_args=url_args,
                params=params,
                is_json=is_json,
                query_params=query_params,
            )

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

        def set_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("set_access_token")

        def order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("order_margins")

        def basket_order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("basket_order_margins")

        def get_virtual_contract_note(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("get_virtual_contract_note")
else:
    class ReadOnlyKiteConnect:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise KiteConfigurationError("kiteconnect library is required")


def _init_facades() -> tuple[type, type]:
    _wrapper_registry: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
    _connector_registry: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()

    _PROHIBITED_ATTRS = frozenset(
        {
            "_target",
            "_client",
            "__client",
            "_raw_client",
            "raw_client",
            "__raw_client",
            "_underlying",
            "_dispatch",
            "__dict__",
            "reqsession",
        }
    )

    class _ReadOnlyKiteWrapper:
        __slots__ = ("__weakref__",)

        def __init__(self, client: Any) -> None:
            _wrapper_registry[self] = client

        def __getattribute__(self, name: str) -> Any:
            if name in _PROHIBITED_ATTRS or (name.startswith("_") and not name.startswith("__")):
                raise PermissionError(f"Access to private attribute '{name}' is forbidden")
            return super().__getattribute__(name)

        def __getattr__(self, name: str) -> Any:
            if name in _BLOCKED_METHODS:
                raise _blocked(name)
            if name not in _READ_ONLY_ALLOWLIST:
                raise PermissionError(f"Kite operation '{name}' is not in the read-only allowlist")

            def bound_call(this: Any, *args: Any, **kwargs: Any) -> Any:
                t = _wrapper_registry.get(this)
                if t is None:
                    raise AttributeError(f"Underlying client not found for '{name}'")
                m = getattr(t, name, None)
                if m is None:
                    raise AttributeError(f"Underlying client has no attribute '{name}'")
                return m(*args, **kwargs)

            bound_call.__name__ = name
            return types.MethodType(bound_call, self)

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

        def set_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("set_access_token")

        def order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("order_margins")

        def basket_order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("basket_order_margins")

        def get_virtual_contract_note(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("get_virtual_contract_note")

        def _post(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_post")

        def _put(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_put")

        def _delete(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_delete")

        def _request(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_request")

    class ZerodhaReadOnlyConnector:
        __slots__ = ("__weakref__",)

        def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
            injected = client is not None
            if client is None:
                key = api_key or os.getenv("KITE_API_KEY", "").strip()
                if not key:
                    raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
                if KiteConnect is None:
                    raise KiteConfigurationError("kiteconnect library is required")
                client = ReadOnlyKiteConnect(api_key=key)
            _connector_registry[self] = (client, injected)
            if not injected:
                token = _safe_get_stored_token(raise_on_error=False)
                if token:
                    try:
                        client.access_token = token
                    except Exception:  # noqa: BLE001
                        pass

        def __getattribute__(self, name: str) -> Any:
            if name in _PROHIBITED_ATTRS or (
                name.startswith("_") and not name.startswith("__") and name != "_require_session"
            ):
                raise PermissionError(f"Access to private attribute '{name}' is forbidden")
            return super().__getattribute__(name)

        @property
        def client(self) -> _ReadOnlyKiteWrapper:
            entry = _connector_registry.get(self)
            tgt, _ = entry if entry is not None else (None, False)
            return _ReadOnlyKiteWrapper(tgt)

        @staticmethod
        def login_url(api_key: str | None = None) -> str:
            key = api_key or os.getenv("KITE_API_KEY", "").strip()
            if not key:
                raise KiteConfigurationError("Set KITE_API_KEY in your environment first.")
            if KiteConnect is None:
                raise KiteConfigurationError("kiteconnect library is required")
            return KiteConnect(api_key=key).login_url()

        @staticmethod
        def store_access_token(token: str) -> None:
            _safe_set_stored_token(token)

        def complete_login(self, *args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Login completion / session generation is forbidden in read-only mode")

        def _require_session(self) -> None:
            entry = _connector_registry.get(self)
            tgt, injected = entry if entry is not None else (None, False)
            tok = getattr(tgt, "access_token", None) if tgt is not None else None
            if isinstance(tok, str) and tok.strip():
                return
            if injected:
                raise KiteConfigurationError(
                    "Injected client must be pre-authenticated with an active access_token"
                )
            stored = _safe_get_stored_token(raise_on_error=True)
            if stored and isinstance(stored, str) and stored.strip():
                if tgt is not None:
                    try:
                        tgt.access_token = stored.strip()
                    except Exception:  # noqa: BLE001
                        pass
                return
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
            entry = _connector_registry.get(self)
            tgt, injected = entry if entry is not None else (None, False)
            if injected:
                return
            _safe_delete_stored_token()
            if tgt is not None:
                if hasattr(tgt, "access_token"):
                    try:
                        tgt.access_token = None
                    except Exception:  # noqa: BLE001
                        pass
                if hasattr(tgt, "reqsession") and hasattr(tgt.reqsession, "headers"):
                    try:
                        tgt.reqsession.headers.pop("Authorization", None)
                    except Exception:  # noqa: BLE001
                        pass

        def __getattr__(self, name: str) -> Any:
            if name in _BLOCKED_METHODS:
                raise _blocked(name)
            if name not in _READ_ONLY_ALLOWLIST:
                raise AttributeError(name)
            self._require_session()
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

        def generate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("generate_session")

        def renew_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("renew_access_token")

        def invalidate_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("invalidate_access_token")

        def invalidate_refresh_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("invalidate_refresh_token")

        def set_access_token(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("set_access_token")

        def order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("order_margins")

        def basket_order_margins(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("basket_order_margins")

        def get_virtual_contract_note(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("get_virtual_contract_note")

        def _post(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_post")

        def _put(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_put")

        def _delete(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_delete")

        def _request(self, *args: Any, **kwargs: Any) -> Any:
            raise _blocked("_request")

    _ReadOnlyKiteWrapper.__name__ = "_ReadOnlyKiteWrapper"
    _ReadOnlyKiteWrapper.__qualname__ = "_ReadOnlyKiteWrapper"
    _ReadOnlyKiteWrapper.__module__ = __name__

    ZerodhaReadOnlyConnector.__name__ = "ZerodhaReadOnlyConnector"
    ZerodhaReadOnlyConnector.__qualname__ = "ZerodhaReadOnlyConnector"
    ZerodhaReadOnlyConnector.__module__ = __name__

    return _ReadOnlyKiteWrapper, ZerodhaReadOnlyConnector


_ReadOnlyKiteWrapper, ZerodhaReadOnlyConnector = _init_facades()
