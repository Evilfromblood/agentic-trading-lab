"""Integration checks against the installed KiteConnect package, with HTTP intercepted."""
from __future__ import annotations

import json

import agentic_trading.zerodha_connector as connector_module
import pytest
from agentic_trading.zerodha_connector import ZerodhaReadOnlyConnector
from kiteconnect import KiteConnect


class _Response:
    status_code = 200
    content = json.dumps({"status": "success", "data": {"user_id": "read-only"}}).encode()
    headers = {"content-type": "application/json"}

    def json(self):
        return json.loads(self.content)


def test_genuine_kite_read_reaches_get_transport_without_mutating_injected_client(monkeypatch):
    raw = KiteConnect(api_key="test-key")
    before_methods = {name: getattr(raw, name) for name in ("profile", "place_order", "_request")}
    requests: list[str] = []

    def intercepted_request(method, *_args, **_kwargs):
        requests.append(method)
        return _Response()

    monkeypatch.setattr(raw.reqsession, "request", intercepted_request)
    monkeypatch.setattr(connector_module, "keyring", None)
    facade = ZerodhaReadOnlyConnector(client=raw).client

    assert facade.profile() == {"user_id": "read-only"}
    assert requests == ["GET"]
    for name, method in before_methods.items():
        assert getattr(raw, name).__func__ is method.__func__


@pytest.mark.parametrize(
    "name",
    ["place_order", "modify_order", "cancel_order", "place_gtt", "place_mf_sip", "generate_session", "_request"],
)
def test_genuine_kite_mutations_are_rejected_before_transport(monkeypatch, name):
    raw = KiteConnect(api_key="test-key")
    transport_calls: list[str] = []
    monkeypatch.setattr(raw.reqsession, "request", lambda method, *_a, **_kw: transport_calls.append(method))
    facade = ZerodhaReadOnlyConnector(client=raw).client

    with pytest.raises(PermissionError):
        if name == "_request":
            facade._request("POST")
        else:
            getattr(facade, name)()
    assert transport_calls == []
