"""Adversarial tests for Milestone 2c Cross-Market Foundation & Stored Replay Fixtures."""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from agentic_trading.market_data.adapters import StandardDictAdapter
from agentic_trading.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionType,
    adjust_candles_for_corporate_actions,
    resolve_symbol_lineage,
)
from agentic_trading.market_data.ingestion import (
    HistoricalDataRequest,
    MarketDataIngestionPipeline,
)
from agentic_trading.market_data.instruments import (
    AssetClass,
    Currency,
    CurrencyMismatchError,
    DuplicateInstrumentError,
    Instrument,
    InstrumentRegistry,
    Money,
    UnknownInstrumentError,
)
from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
    ExchangeCalendar,
)
from agentic_trading.market_data.provider import (
    ProviderPayloadError,
    ProviderResponse,
    SyntheticMarketDataProvider,
)
from agentic_trading.market_data.replay_fixtures import (
    _DEFAULT_HMAC_KEY,
    FixtureIntegrityError,
    StoredReplayFixtureProvider,
    _compute_fixture_hmac,
    save_replay_fixture,
)


def test_money_arithmetic_same_currency() -> None:
    m1 = Money(Decimal("100.50"), Currency.INR)
    m2 = Money(Decimal("50.25"), Currency.INR)

    added = m1 + m2
    assert added.amount == Decimal("150.75")
    assert added.currency == Currency.INR

    subbed = m1 - m2
    assert subbed.amount == Decimal("50.25")
    assert subbed.currency == Currency.INR

    neg = -m1
    assert neg.amount == Decimal("-100.50")
    assert neg.currency == Currency.INR


def test_money_cross_currency_arithmetic_raises_error() -> None:
    inr = Money(Decimal("100.00"), Currency.INR)
    usd = Money(Decimal("100.00"), Currency.USD)

    with pytest.raises(CurrencyMismatchError):
        _ = inr + usd

    with pytest.raises(CurrencyMismatchError):
        _ = inr - usd


def test_money_scalar_multiplication() -> None:
    m = Money(Decimal("25.00"), Currency.USD)

    m_dec = m * Decimal("2.5")
    assert m_dec.amount == Decimal("62.500")

    m_int = m * 3
    assert m_int.amount == Decimal("75.00")

    m_rmul = 4 * m
    assert m_rmul.amount == Decimal("100.00")


def test_money_type_rejections() -> None:
    with pytest.raises(TypeError):
        Money(10.5, Currency.INR)

    with pytest.raises(TypeError):
        Money(True, Currency.INR)

    with pytest.raises(TypeError):
        Money(b"100", Currency.INR)

    with pytest.raises(ValueError):
        Money(Decimal("NaN"), Currency.INR)

    with pytest.raises(ValueError):
        Money(Decimal("Infinity"), Currency.INR)

    with pytest.raises(TypeError):
        Money(Decimal("100"), "INR")

    m = Money(Decimal("10.00"), Currency.INR)
    with pytest.raises(TypeError):
        _ = m * 1.5

    with pytest.raises(TypeError):
        _ = m * True

    with pytest.raises(ValueError):
        _ = m * Decimal("NaN")


def test_instrument_exchange_currency_pairing_enforced() -> None:
    with pytest.raises(CurrencyMismatchError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.USD)

    with pytest.raises(CurrencyMismatchError):
        Instrument(symbol="TCS", exchange=Exchange.BSE, currency=Currency.USD)

    with pytest.raises(CurrencyMismatchError):
        Instrument(symbol="AAPL", exchange=Exchange.NASDAQ, currency=Currency.INR)

    with pytest.raises(CurrencyMismatchError):
        Instrument(symbol="IBM", exchange=Exchange.NYSE, currency=Currency.INR)


def test_instrument_valid_creation_and_field_normalization() -> None:
    inst_nse = Instrument(
        symbol="infy",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        asset_class=AssetClass.EQUITY,
        tick_size=Decimal("0.05"),
        lot_size=1,
        isin="INE009A01021",
        provider_tokens={"kite": "408065"},
    )
    assert inst_nse.symbol == "INFY"
    assert inst_nse.currency == Currency.INR
    assert inst_nse.provider_tokens["kite"] == "408065"

    inst_us = Instrument(
        symbol="aapl",
        exchange=Exchange.NASDAQ,
        currency=Currency.USD,
        tick_size=Decimal("0.01"),
    )
    assert inst_us.symbol == "AAPL"
    assert inst_us.currency == Currency.USD


def test_instrument_invalid_attributes_fail_closed() -> None:
    with pytest.raises(ValueError):
        Instrument(symbol="", exchange=Exchange.NSE, currency=Currency.INR)

    with pytest.raises(ValueError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, tick_size=Decimal("-0.01"))

    with pytest.raises(ValueError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, tick_size=Decimal("0"))

    with pytest.raises(ValueError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=0)

    with pytest.raises(ValueError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=True)


def test_instrument_registry_operations() -> None:
    registry = InstrumentRegistry()

    inst1 = Instrument(
        symbol="INFY",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        provider_tokens={"kite": "408065"},
    )
    inst2 = Instrument(
        symbol="AAPL",
        exchange=Exchange.NASDAQ,
        currency=Currency.USD,
        provider_tokens={"finnhub": "AAPL"},
    )

    registry.register(inst1)
    registry.register(inst2)

    assert registry.get(Exchange.NSE, "INFY") == inst1
    assert registry.get(Exchange.NSE, "infy") == inst1
    assert registry.get(Exchange.NASDAQ, "AAPL") == inst2

    assert registry.get_by_token("kite", "408065") == inst1
    assert registry.get_by_token("finnhub", "AAPL") == inst2

    with pytest.raises(DuplicateInstrumentError):
        registry.register(inst1)

    duplicate_token_inst = Instrument(
        symbol="INFY_CLONE",
        exchange=Exchange.BSE,
        currency=Currency.INR,
        provider_tokens={"kite": "408065"},
    )
    with pytest.raises(DuplicateInstrumentError):
        registry.register(duplicate_token_inst)

    with pytest.raises(UnknownInstrumentError):
        registry.get(Exchange.NSE, "RELIANCE")

    with pytest.raises(UnknownInstrumentError):
        registry.get_by_token("kite", "999999")

    nse_list = registry.list_by_exchange(Exchange.NSE)
    assert len(nse_list) == 1
    assert nse_list[0] == inst1

    nasdaq_list = registry.list_by_exchange(Exchange.NASDAQ)
    assert len(nasdaq_list) == 1
    assert nasdaq_list[0] == inst2

    assert len(registry.list_by_exchange(Exchange.BSE)) == 0


def test_corporate_action_creation_and_currency_validation() -> None:
    ca_split = CorporateAction(
        exchange=Exchange.NSE,
        symbol="TCS",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 6, 1),
        adjustment_factor=Decimal("0.5"),
    )
    assert ca_split.adjustment_factor == Decimal("0.5")

    ca_div = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.DIVIDEND,
        effective_date=date(2026, 7, 1),
        cash_amount=Money(Decimal("15.50"), Currency.INR),
    )
    assert ca_div.cash_amount is not None
    assert ca_div.cash_amount.amount == Decimal("15.50")

    with pytest.raises(CurrencyMismatchError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="INFY",
            action_type=CorporateActionType.DIVIDEND,
            effective_date=date(2026, 7, 1),
            cash_amount=Money(Decimal("1.50"), Currency.USD),
        )

    with pytest.raises(ValueError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="INFY",
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2026, 6, 1),
            adjustment_factor=Decimal("0"),
        )

    with pytest.raises(ValueError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="INFY",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2026, 6, 1),
            new_symbol="INFY",
        )


def test_symbol_lineage_resolution_forward_and_backward() -> None:
    actions = [
        CorporateAction(
            exchange=Exchange.NASDAQ,
            symbol="FB",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2022, 6, 9),
            new_symbol="META",
        ),
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="UTIBANK",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2007, 7, 30),
            new_symbol="AXISBANK",
        ),
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="AXISBANK",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2025, 1, 1),
            new_symbol="AXIS",
        ),
    ]

    res_forward = resolve_symbol_lineage(Exchange.NASDAQ, "FB", date(2023, 1, 1), actions)
    assert res_forward == "META"

    res_backward = resolve_symbol_lineage(Exchange.NASDAQ, "META", date(2020, 1, 1), actions)
    assert res_backward == "FB"

    res_same = resolve_symbol_lineage(Exchange.NASDAQ, "META", date(2023, 1, 1), actions)
    assert res_same == "META"

    res_multi_fwd = resolve_symbol_lineage(Exchange.NSE, "UTIBANK", date(2026, 1, 1), actions)
    assert res_multi_fwd == "AXIS"

    res_multi_mid = resolve_symbol_lineage(Exchange.NSE, "UTIBANK", date(2015, 1, 1), actions)
    assert res_multi_mid == "AXISBANK"

    res_multi_bwd = resolve_symbol_lineage(Exchange.NSE, "AXIS", date(2005, 1, 1), actions)
    assert res_multi_bwd == "UTIBANK"


def test_symbol_lineage_cycle_detection() -> None:
    cyclic_actions = [
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="A",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2024, 1, 1),
            new_symbol="B",
        ),
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="B",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2025, 1, 1),
            new_symbol="A",
        ),
    ]

    with pytest.raises(ValueError, match="Cyclic symbol change"):
        resolve_symbol_lineage(Exchange.NSE, "A", date(2026, 1, 1), cyclic_actions)


def test_adjust_candles_for_corporate_actions_split_and_bonus() -> None:
    dt1 = datetime(2026, 5, 20, 9, 15, tzinfo=IST)
    dt2 = datetime(2026, 6, 10, 9, 15, tzinfo=IST)

    c1 = Candle(
        symbol="TCS",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("4000.00"),
        high=Decimal("4100.00"),
        low=Decimal("3950.00"),
        close=Decimal("4050.00"),
        volume=100000,
        timestamp=dt1,
        source="TEST",
        retrieval_timestamp=dt1 + timedelta(hours=7),
    )
    c2 = Candle(
        symbol="TCS",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("2020.00"),
        high=Decimal("2060.00"),
        low=Decimal("2000.00"),
        close=Decimal("2050.00"),
        volume=200000,
        timestamp=dt2,
        source="TEST",
        retrieval_timestamp=dt2 + timedelta(hours=7),
    )

    split_action = CorporateAction(
        exchange=Exchange.NSE,
        symbol="TCS",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 6, 1),
        adjustment_factor=Decimal("0.5"),
    )

    adjusted = adjust_candles_for_corporate_actions(
        candles=[c1, c2],
        actions=[split_action],
        tick_size=Decimal("0.05"),
    )

    assert len(adjusted) == 2
    adj_c1 = adjusted[0]
    assert adj_c1.open == Decimal("2000.00")
    assert adj_c1.high == Decimal("2050.00")
    assert adj_c1.low == Decimal("1975.00")
    assert adj_c1.close == Decimal("2025.00")
    assert adj_c1.volume == 200000

    adj_c2 = adjusted[1]
    assert adj_c2.open == Decimal("2020.00")
    assert adj_c2.high == Decimal("2060.00")
    assert adj_c2.low == Decimal("2000.00")
    assert adj_c2.close == Decimal("2050.00")
    assert adj_c2.volume == 200000


def test_stored_replay_fixture_round_trip_and_ingestion_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        t1 = t0 + timedelta(minutes=5)
        t2 = t0 + timedelta(minutes=10)

        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            },
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t1.isoformat(),
                "open": "1505.00",
                "high": "1515.00",
                "low": "1500.00",
                "close": "1512.00",
                "volume": 6000,
            },
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t2.isoformat(),
                "open": "1512.00",
                "high": "1520.00",
                "low": "1510.00",
                "close": "1518.00",
                "volume": 5500,
            },
        ]

        recorded_time = t2 + timedelta(hours=1)
        response = ProviderResponse(
            success=True,
            source="TEST_FIXTURE_SRC",
            retrieval_timestamp=recorded_time,
            records=tuple(records),
        )

        manifest = save_replay_fixture(
            directory=tmp_dir,
            fixture_id="infy_sample_m5",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )

        assert manifest.fixture_id == "infy_sample_m5"
        assert manifest.record_count == 3
        assert len(manifest.payload_sha256) == 64

        provider = StoredReplayFixtureProvider(
            directory=tmp_dir,
            fixture_id="infy_sample_m5",
        )
        assert provider.source_name == "TEST_FIXTURE_SRC"

        req = HistoricalDataRequest(
            symbol="INFY",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            start_time=t0,
            end_time=t2 + timedelta(minutes=5),
        )

        prov_resp = provider.fetch_historical(req)
        assert prov_resp.success is True
        assert len(prov_resp.records) == 3

        adapter = StandardDictAdapter(source_name=provider.source_name)
        pipeline = MarketDataIngestionPipeline(provider=provider, adapter=adapter)

        cal = ExchangeCalendar(
            exchange=Exchange.NSE,
            trading_days=frozenset({date(2026, 11, 2)}),
            coverage_start=date(2026, 11, 2),
            coverage_end=date(2026, 11, 2),
            complete=True,
        )

        ingest_res = pipeline.ingest_historical(
            request=req,
            now=recorded_time + timedelta(minutes=5),
            calendar=cal,
            check_gaps=True,
        )

        assert ingest_res.success is True
        assert len(ingest_res.candles) == 3
        assert ingest_res.raw_record_count == 3
        assert ingest_res.candles[0].open == Decimal("1500.00")
        assert ingest_res.candles[-1].close == Decimal("1518.00")

        latest_resp = provider.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)
        assert latest_resp.success is True
        assert len(latest_resp.records) == 1
        assert latest_resp.records[0]["timestamp"] == t2.isoformat()


def test_stored_replay_fixture_tamper_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            }
        ]
        response = ProviderResponse(
            success=True,
            source="TAMPER_SRC",
            retrieval_timestamp=t0 + timedelta(minutes=15),
            records=tuple(records),
        )
        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="tamper_test",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )

        payload_file = Path(tmp_dir) / "tamper_test.payload.json"
        raw_bytes = payload_file.read_bytes()
        tampered_bytes = raw_bytes.replace(b"1500.00", b"1599.99")
        payload_file.write_bytes(tampered_bytes)

        provider = StoredReplayFixtureProvider(tmp_dir, "tamper_test")
        req = HistoricalDataRequest(
            symbol="INFY",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            start_time=t0,
            end_time=t0 + timedelta(minutes=5),
        )
        with pytest.raises(FixtureIntegrityError, match="digest mismatch"):
            provider.fetch_historical(req)


def test_stored_replay_fixture_security_and_missing_files() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(FixtureIntegrityError):
            StoredReplayFixtureProvider(tmp_dir, "../escape_path")

        with pytest.raises(FixtureIntegrityError):
            StoredReplayFixtureProvider(tmp_dir, "invalid/id")

        provider = StoredReplayFixtureProvider(tmp_dir, "non_existent_fixture")
        req = HistoricalDataRequest(
            symbol="INFY",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            start_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            end_time=datetime(2026, 11, 2, 9, 30, tzinfo=IST),
        )
        with pytest.raises(FixtureIntegrityError, match="Missing fixture manifest"):
            provider.fetch_historical(req)



def test_currency_and_asset_class_missing_case_insensitivity() -> None:
    assert Currency("inr") == Currency.INR
    assert Currency("usd") == Currency.USD
    with pytest.raises(ValueError):
        Currency("invalid_currency")

    assert AssetClass("equity") == AssetClass.EQUITY
    assert AssetClass("etf") == AssetClass.ETF
    assert AssetClass("index") == AssetClass.INDEX
    with pytest.raises(ValueError):
        AssetClass("crypto")

    assert CorporateActionType("split") == CorporateActionType.SPLIT
    assert CorporateActionType("bonus") == CorporateActionType.BONUS
    assert CorporateActionType("dividend") == CorporateActionType.DIVIDEND
    assert CorporateActionType("symbol_change") == CorporateActionType.SYMBOL_CHANGE
    with pytest.raises(ValueError):
        CorporateActionType("merger")


def test_money_not_implemented_branches() -> None:
    m = Money(Decimal("10.00"), Currency.INR)
    with pytest.raises(TypeError):
        _ = m + "10"
    with pytest.raises(TypeError):
        _ = m - "5"
    with pytest.raises(TypeError):
        _ = m * "scalar"


def test_instrument_and_registry_type_validations() -> None:
    with pytest.raises(TypeError):
        Instrument(symbol="INFY", exchange="NSE", currency=Currency.INR)

    with pytest.raises(TypeError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency="INR")

    with pytest.raises(TypeError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, asset_class="EQUITY")

    with pytest.raises(ValueError):
        Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, isin="")

    reg = InstrumentRegistry()
    with pytest.raises(TypeError):
        reg.register("not_an_instrument")

    with pytest.raises(TypeError):
        reg.get("NSE", "INFY")

    with pytest.raises(ValueError):
        reg.get(Exchange.NSE, "")

    with pytest.raises(ValueError):
        reg.get_by_token("", "token")

    with pytest.raises(ValueError):
        reg.get_by_token("provider", "")

    with pytest.raises(TypeError):
        reg.list_by_exchange("NSE")


def test_corporate_action_type_validations() -> None:
    with pytest.raises(TypeError):
        CorporateAction(exchange="NSE", symbol="INFY", action_type=CorporateActionType.SPLIT, effective_date=date(2026, 1, 1))

    with pytest.raises(TypeError):
        CorporateAction(exchange=Exchange.NSE, symbol="INFY", action_type="SPLIT", effective_date=date(2026, 1, 1))

    with pytest.raises(TypeError):
        CorporateAction(exchange=Exchange.NSE, symbol="INFY", action_type=CorporateActionType.SPLIT, effective_date="2026-01-01")

    with pytest.raises(TypeError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="INFY",
            action_type=CorporateActionType.DIVIDEND,
            effective_date=date(2026, 1, 1),
            cash_amount="10",
        )

    ca_with_sym = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 1, 1),
        new_symbol="infy_new",
    )
    assert ca_with_sym.new_symbol == "INFY_NEW"


def test_resolve_symbol_lineage_type_validations() -> None:
    with pytest.raises(TypeError):
        resolve_symbol_lineage("NSE", "INFY", date(2026, 1, 1), ())

    with pytest.raises(ValueError):
        resolve_symbol_lineage(Exchange.NSE, "", date(2026, 1, 1), ())

    with pytest.raises(TypeError):
        resolve_symbol_lineage(Exchange.NSE, "INFY", "2026-01-01", ())


def test_adjust_candles_invalid_tick_size() -> None:
    c = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("1500"),
        high=Decimal("1520"),
        low=Decimal("1490"),
        close=Decimal("1510"),
        volume=1000,
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=IST),
        source="TEST",
        retrieval_timestamp=datetime(2026, 1, 1, 16, 0, tzinfo=IST),
    )
    with pytest.raises(ValueError):
        adjust_candles_for_corporate_actions([c], (), tick_size=Decimal("-0.01"))

    with pytest.raises(ValueError):
        adjust_candles_for_corporate_actions([c], (), tick_size=Decimal("0"))

    with pytest.raises(ValueError):
        adjust_candles_for_corporate_actions([c], (), tick_size=0.01)


def test_fixture_manifest_and_save_validation_branches() -> None:
    with pytest.raises(FixtureIntegrityError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="../bad",
            source="SRC",
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(ValueError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="",
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(TypeError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="SRC",
            exchange="NSE",
            symbol="INFY",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(ValueError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="SRC",
            exchange=Exchange.NSE,
            symbol="",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(TypeError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="SRC",
            exchange=Exchange.NSE,
            symbol="INFY",
            interval="5m",
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(ValueError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="SRC",
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=-1,
            payload_sha256="a" * 64,
        )

    with pytest.raises(FixtureIntegrityError):
        from agentic_trading.market_data.replay_fixtures import FixtureManifest
        FixtureManifest(
            fixture_id="valid_id",
            source="SRC",
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            recorded_at=datetime(2026, 1, 1, tzinfo=IST),
            record_count=1,
            payload_sha256="short_sha",
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(TypeError):
            save_replay_fixture(
                directory=tmp_dir,
                fixture_id="test",
                response="not_response",
                exchange=Exchange.NSE,
                symbol="INFY",
                interval=CandleInterval.M5,
            )

        failed_response = ProviderResponse(
            success=False,
            source="SRC",
            retrieval_timestamp=datetime(2026, 1, 1, tzinfo=IST),
            error_message="failed",
        )
        with pytest.raises(ValueError):
            save_replay_fixture(
                directory=tmp_dir,
                fixture_id="test",
                response=failed_response,
                exchange=Exchange.NSE,
                symbol="INFY",
                interval=CandleInterval.M5,
            )


def test_stored_replay_fixture_corrupt_manifest_and_payload() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        m_file = base / "corrupt_manifest.manifest.json"
        p_file = base / "corrupt_manifest.payload.json"
        p_file.write_text("[]", encoding="utf-8")
        m_file.write_text("{invalid json", encoding="utf-8")

        p = StoredReplayFixtureProvider(tmp_dir, "corrupt_manifest")
        with pytest.raises(FixtureIntegrityError, match="Corrupt manifest JSON"):
            p.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        m_file = base / "corrupt_payload.manifest.json"
        p_file = base / "corrupt_payload.payload.json"
        bad_bytes = b"not json"
        p_file.write_bytes(bad_bytes)
        recorded_at_str = datetime(2026, 1, 1, tzinfo=IST).isoformat()
        bad_sha = _compute_fixture_hmac(
            _DEFAULT_HMAC_KEY,
            "corrupt_payload",
            "SRC",
            Exchange.NSE.value,
            "INFY",
            CandleInterval.M5.value,
            recorded_at_str,
            0,
            bad_bytes,
        )
        manifest_data = {
            "fixture_id": "corrupt_payload",
            "source": "SRC",
            "exchange": "NSE",
            "symbol": "INFY",
            "interval": "5m",
            "recorded_at": recorded_at_str,
            "record_count": 0,
            "payload_sha256": bad_sha,
        }
        import json
        m_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        from agentic_trading.market_data.provider import ProviderPayloadError
        p = StoredReplayFixtureProvider(tmp_dir, "corrupt_payload")
        with pytest.raises(ProviderPayloadError, match="Corrupt payload JSON"):
            p.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        m_file = base / "not_list.manifest.json"
        p_file = base / "not_list.payload.json"
        bad_bytes = b'{"not": "a list"}'
        p_file.write_bytes(bad_bytes)
        recorded_at_str = datetime(2026, 1, 1, tzinfo=IST).isoformat()
        bad_sha = _compute_fixture_hmac(
            _DEFAULT_HMAC_KEY,
            "not_list",
            "SRC",
            Exchange.NSE.value,
            "INFY",
            CandleInterval.M5.value,
            recorded_at_str,
            0,
            bad_bytes,
        )
        manifest_data = {
            "fixture_id": "not_list",
            "source": "SRC",
            "exchange": "NSE",
            "symbol": "INFY",
            "interval": "5m",
            "recorded_at": recorded_at_str,
            "record_count": 0,
            "payload_sha256": bad_sha,
        }
        import json
        m_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        from agentic_trading.market_data.provider import ProviderPayloadError
        p = StoredReplayFixtureProvider(tmp_dir, "not_list")
        with pytest.raises(ProviderPayloadError, match="must be a list"):
            p.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        m_file = base / "not_mapping.manifest.json"
        p_file = base / "not_mapping.payload.json"
        bad_bytes = b'["not a mapping"]'
        p_file.write_bytes(bad_bytes)
        recorded_at_str = datetime(2026, 1, 1, tzinfo=IST).isoformat()
        bad_sha = _compute_fixture_hmac(
            _DEFAULT_HMAC_KEY,
            "not_mapping",
            "SRC",
            Exchange.NSE.value,
            "INFY",
            CandleInterval.M5.value,
            recorded_at_str,
            1,
            bad_bytes,
        )
        manifest_data = {
            "fixture_id": "not_mapping",
            "source": "SRC",
            "exchange": "NSE",
            "symbol": "INFY",
            "interval": "5m",
            "recorded_at": recorded_at_str,
            "record_count": 1,
            "payload_sha256": bad_sha,
        }
        import json
        m_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        from agentic_trading.market_data.provider import ProviderPayloadError
        p = StoredReplayFixtureProvider(tmp_dir, "not_mapping")
        with pytest.raises(ProviderPayloadError, match="must be a Mapping"):
            p.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        m_file = base / "count_mismatch.manifest.json"
        p_file = base / "count_mismatch.payload.json"
        bad_bytes = b'[]'
        p_file.write_bytes(bad_bytes)
        recorded_at_str = datetime(2026, 1, 1, tzinfo=IST).isoformat()
        bad_sha = _compute_fixture_hmac(
            _DEFAULT_HMAC_KEY,
            "count_mismatch",
            "SRC",
            Exchange.NSE.value,
            "INFY",
            CandleInterval.M5.value,
            recorded_at_str,
            5,
            bad_bytes,
        )
        manifest_data = {
            "fixture_id": "count_mismatch",
            "source": "SRC",
            "exchange": "NSE",
            "symbol": "INFY",
            "interval": "5m",
            "recorded_at": recorded_at_str,
            "record_count": 5,
            "payload_sha256": bad_sha,
        }
        import json
        m_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        p = StoredReplayFixtureProvider(tmp_dir, "count_mismatch")
        with pytest.raises(FixtureIntegrityError, match="Record count mismatch"):
            p.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)


def test_stored_replay_fixture_fetch_latest_empty_match() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            }
        ]
        response = ProviderResponse(
            success=True,
            source="SRC",
            retrieval_timestamp=t0 + timedelta(minutes=15),
            records=tuple(records),
        )
        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="empty_match_test",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )
        provider = StoredReplayFixtureProvider(tmp_dir, "empty_match_test")
        latest = provider.fetch_latest("NONEXISTENT", Exchange.NSE, CandleInterval.M5)
        assert latest.success is True
        assert len(latest.records) == 0


def test_replay_fixture_h5_historical_filtering_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            }
        ]
        response = ProviderResponse(
            success=True,
            source="SRC",
            retrieval_timestamp=t0 + timedelta(minutes=15),
            records=tuple(records),
        )
        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="h5_filter_test",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )
        provider = StoredReplayFixtureProvider(tmp_dir, "h5_filter_test")

        res_diff_symbol = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="TCS",
                exchange=Exchange.NSE,
                interval=CandleInterval.M5,
                start_time=t0,
                end_time=t0 + timedelta(minutes=10),
            )
        )
        assert res_diff_symbol.success is True
        assert len(res_diff_symbol.records) == 0

        res_diff_exchange = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="INFY",
                exchange=Exchange.BSE,
                interval=CandleInterval.M5,
                start_time=t0,
                end_time=t0 + timedelta(minutes=10),
            )
        )
        assert res_diff_exchange.success is True
        assert len(res_diff_exchange.records) == 0

        res_diff_interval = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="INFY",
                exchange=Exchange.NSE,
                interval=CandleInterval.M15,
                start_time=t0,
                end_time=t0 + timedelta(minutes=10),
            )
        )
        assert res_diff_interval.success is True
        assert len(res_diff_interval.records) == 0

        res_match = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="INFY",
                exchange=Exchange.NSE,
                interval=CandleInterval.M5,
                start_time=t0,
                end_time=t0 + timedelta(minutes=10),
            )
        )
        assert res_match.success is True
        assert len(res_match.records) == 1


def test_replay_fixture_h6_close_time_slicing_excludes_inprogress() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            }
        ]
        response = ProviderResponse(
            success=True,
            source="SRC",
            retrieval_timestamp=t0 + timedelta(minutes=15),
            records=tuple(records),
        )
        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="h6_slicing_test",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )
        provider = StoredReplayFixtureProvider(tmp_dir, "h6_slicing_test")

        hist_before_close = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="INFY",
                exchange=Exchange.NSE,
                interval=CandleInterval.M5,
                start_time=t0,
                end_time=t0 + timedelta(minutes=4),
            )
        )
        assert len(hist_before_close.records) == 0

        hist_at_close = provider.fetch_historical(
            HistoricalDataRequest(
                symbol="INFY",
                exchange=Exchange.NSE,
                interval=CandleInterval.M5,
                start_time=t0,
                end_time=t0 + timedelta(minutes=5),
            )
        )
        assert len(hist_at_close.records) == 1

        latest_before_close = provider.fetch_latest(
            "INFY", Exchange.NSE, CandleInterval.M5, now=t0 + timedelta(minutes=4)
        )
        assert len(latest_before_close.records) == 0

        latest_at_close = provider.fetch_latest(
            "INFY", Exchange.NSE, CandleInterval.M5, now=t0 + timedelta(minutes=5)
        )
        assert len(latest_at_close.records) == 1


def test_replay_fixture_h7_l7_hmac_and_manifest_guards() -> None:
    import json
    with tempfile.TemporaryDirectory() as tmp_dir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        records = [
            {
                "symbol": "INFY",
                "exchange": Exchange.NSE.value,
                "interval": CandleInterval.M5.value,
                "timestamp": t0.isoformat(),
                "open": "1500.00",
                "high": "1510.00",
                "low": "1495.00",
                "close": "1505.00",
                "volume": 5000,
            }
        ]
        response = ProviderResponse(
            success=True,
            source="SRC",
            retrieval_timestamp=t0 + timedelta(minutes=15),
            records=tuple(records),
        )

        custom_key = b"custom-secret-key-12345"
        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="custom_key_fixture",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            hmac_key=custom_key,
        )

        prov_default = StoredReplayFixtureProvider(tmp_dir, "custom_key_fixture")
        with pytest.raises(FixtureIntegrityError, match="HMAC digest mismatch"):
            prov_default.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

        prov_custom = StoredReplayFixtureProvider(tmp_dir, "custom_key_fixture", hmac_key=custom_key)
        assert len(prov_custom.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5).records) == 1

        with pytest.raises(FixtureIntegrityError, match="already exists"):
            save_replay_fixture(
                directory=tmp_dir,
                fixture_id="custom_key_fixture",
                response=response,
                exchange=Exchange.NSE,
                symbol="INFY",
                interval=CandleInterval.M5,
                hmac_key=custom_key,
                overwrite=False,
            )

        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="custom_key_fixture",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
            hmac_key=custom_key,
            overwrite=True,
        )

        manifest_path = Path(tmp_dir) / "custom_key_fixture.manifest.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_data["exchange"] = "BSE"
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

        with pytest.raises(FixtureIntegrityError, match="HMAC digest mismatch"):
            prov_custom.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

        del manifest_data["recorded_at"]
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        with pytest.raises(FixtureIntegrityError, match="Missing required manifest field"):
            prov_custom.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)

        save_replay_fixture(
            directory=tmp_dir,
            fixture_id="missing_ts_fixture",
            response=response,
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.M5,
        )
        payload_path = Path(tmp_dir) / "missing_ts_fixture.payload.json"
        m_path = Path(tmp_dir) / "missing_ts_fixture.manifest.json"
        bad_payload = json.dumps([{"symbol": "INFY", "close": "1505.00"}]).encode("utf-8")
        payload_path.write_bytes(bad_payload)

        m_dict = json.loads(m_path.read_text(encoding="utf-8"))
        bad_sha = _compute_fixture_hmac(
            _DEFAULT_HMAC_KEY,
            "missing_ts_fixture",
            "SRC",
            Exchange.NSE.value,
            "INFY",
            CandleInterval.M5.value,
            m_dict["recorded_at"],
            m_dict["record_count"],
            bad_payload,
        )
        m_dict["payload_sha256"] = bad_sha
        m_path.write_text(json.dumps(m_dict), encoding="utf-8")

        p_missing_ts = StoredReplayFixtureProvider(tmp_dir, "missing_ts_fixture")
        with pytest.raises(ProviderPayloadError, match="missing timestamp"):
            p_missing_ts.fetch_latest("INFY", Exchange.NSE, CandleInterval.M5)


def test_corporate_action_m9_duplicate_deduplication() -> None:
    t0 = datetime(2026, 5, 1, 9, 15, tzinfo=IST)
    candle = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("2000.00"),
        high=Decimal("2050.00"),
        low=Decimal("1990.00"),
        close=Decimal("2020.00"),
        volume=1000,
        timestamp=t0,
        source="SRC",
        retrieval_timestamp=t0 + timedelta(days=1),
    )
    action = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 6, 1),
        adjustment_factor=Decimal("2.0"),
    )
    adjusted_candles = adjust_candles_for_corporate_actions([candle], [action, action])
    assert len(adjusted_candles) == 1
    assert adjusted_candles[0].close == Decimal("4040.00")
    assert adjusted_candles[0].volume == 500


def test_symbol_lineage_l5_isolated_unrelated_cycle() -> None:
    actions = [
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="CYCLE_A",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2026, 1, 1),
            new_symbol="CYCLE_B",
        ),
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="CYCLE_B",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2026, 2, 1),
            new_symbol="CYCLE_A",
        ),
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="INFY_OLD",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2026, 3, 1),
            new_symbol="INFY",
        ),
    ]
    resolved = resolve_symbol_lineage(Exchange.NSE, "INFY", date(2026, 1, 1), actions)
    assert resolved == "INFY_OLD"


def test_instrument_registry_l3_thread_safety() -> None:
    import concurrent.futures

    registry = InstrumentRegistry()
    instruments = [
        Instrument(
            symbol=f"SYM{i}",
            exchange=Exchange.NSE,
            currency=Currency.INR,
            provider_tokens={"provider1": f"tok_{i}"},
        )
        for i in range(100)
    ]

    def register_inst(inst: Instrument) -> None:
        registry.register(inst)

    def read_inst(inst: Instrument) -> None:
        fetched = registry.get(inst.exchange, inst.symbol)
        assert fetched == inst
        by_tok = registry.get_by_token("provider1", f"tok_{inst.symbol[3:]}")
        assert by_tok == inst

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(register_inst, instruments))
        list(executor.map(read_inst, instruments))

    assert len(registry.list_by_exchange(Exchange.NSE)) == 100


def test_instrument_l4_datetime_rejection() -> None:
    inst = Instrument(
        symbol="INFY",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        listed_date=date(2020, 1, 1),
        delisted_date=date(2030, 1, 1),
    )
    dt_val = datetime(2026, 1, 1, 10, 0, tzinfo=IST)

    with pytest.raises(TypeError, match="as_of_date must be a date, not datetime"):
        inst.is_active_on(dt_val)

    registry = InstrumentRegistry()
    registry.register(inst)

    with pytest.raises(TypeError, match="as_of_date must be a date, not datetime"):
        registry.get_as_of(Exchange.NSE, "INFY", dt_val)

    with pytest.raises(TypeError, match="as_of_date must be a date, not datetime"):
        registry.list_active_on(Exchange.NSE, dt_val)


def test_r5_replay_fixture_id_mismatch_and_naive_dt() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        rec = {
            "symbol": "INFY",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t0.isoformat(),
            "open": "1500.00",
            "high": "1510.00",
            "low": "1490.00",
            "close": "1505.00",
            "volume": 1000,
        }
        resp = ProviderResponse(success=True, source="TEST_SRC", retrieval_timestamp=t0, records=(rec,))
        save_replay_fixture(tmpdir, "fixture_orig", resp, Exchange.NSE, "INFY", CandleInterval.M5)

        man_path = Path(tmpdir) / "fixture_orig.manifest.json"
        pay_path = Path(tmpdir) / "fixture_orig.payload.json"
        man_text = man_path.read_text(encoding="utf-8")
        pay_bytes = pay_path.read_bytes()

        (Path(tmpdir) / "fixture_renamed.manifest.json").write_text(man_text, encoding="utf-8")
        (Path(tmpdir) / "fixture_renamed.payload.json").write_bytes(pay_bytes)

        p_renamed = StoredReplayFixtureProvider(tmpdir, "fixture_renamed")
        with pytest.raises(FixtureIntegrityError, match="Fixture identity mismatch"):
            p_renamed.fetch_historical(
                HistoricalDataRequest("INFY", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=5))
            )

        import json
        man_dict = json.loads(man_text)
        man_dict["recorded_at"] = "2026-11-02T09:15:00"
        (Path(tmpdir) / "fixture_naive.manifest.json").write_text(json.dumps(man_dict), encoding="utf-8")
        (Path(tmpdir) / "fixture_naive.payload.json").write_bytes(pay_bytes)

        p_naive = StoredReplayFixtureProvider(tmpdir, "fixture_naive")
        with pytest.raises(FixtureIntegrityError, match="timezone-naive"):
            p_naive.fetch_historical(
                HistoricalDataRequest("INFY", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=5))
            )


def test_r6_synthetic_provider_filtering_and_slicing() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"symbol": "INFY", "exchange": "NSE", "interval": "5m", "timestamp": t0.isoformat(), "open": "1500", "high": "1510", "low": "1490", "close": "1505", "volume": 100},
        {"symbol": "RELIANCE", "exchange": "BSE", "interval": "5m", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "15m", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"exchange": "NSE", "interval": "5m", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"symbol": "RELIANCE", "interval": "5m", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"symbol": "RELIANCE", "exchange": "NSE", "timestamp": t0.isoformat(), "open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100},
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "timestamp": (t0 + timedelta(minutes=5)).isoformat(), "open": "2505", "high": "2515", "low": "2495", "close": "2510", "volume": 100},
    ]
    p = SyntheticMarketDataProvider(records=records)

    req = HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=5))
    resp_hist = p.fetch_historical(req)
    assert resp_hist.success is True
    assert len(resp_hist.records) == 1
    assert resp_hist.records[0]["symbol"] == "RELIANCE"
    assert resp_hist.records[0]["timestamp"] == t0.isoformat()

    resp_latest = p.fetch_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=t0 + timedelta(minutes=7))
    assert resp_latest.success is True
    assert len(resp_latest.records) == 1
    assert resp_latest.records[0]["timestamp"] == t0.isoformat()


def test_r7_corporate_actions_dedup_and_deep_lineage() -> None:
    t = datetime(2026, 11, 2, 10, 0, tzinfo=IST)
    candle = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("1000.00"),
        high=Decimal("1010.00"),
        low=Decimal("990.00"),
        close=Decimal("1005.00"),
        volume=10000,
        timestamp=t,
        source="TEST",
        retrieval_timestamp=t + timedelta(hours=6),
    )
    act1 = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 11, 5),
        announcement_date=date(2026, 10, 20),
        adjustment_factor=Decimal("0.5"),
    )
    act2_duplicate_diff_announcement = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 11, 5),
        announcement_date=date(2026, 10, 25),
        adjustment_factor=Decimal("0.5"),
    )
    adjusted = adjust_candles_for_corporate_actions([candle], [act1, act2_duplicate_diff_announcement])
    assert len(adjusted) == 1
    assert adjusted[0].open == Decimal("500.00")
    assert adjusted[0].volume == 20000

    chain_actions = [
        CorporateAction(
            exchange=Exchange.NSE,
            symbol=f"SYM_{i}",
            action_type=CorporateActionType.SYMBOL_CHANGE,
            effective_date=date(2026, 1, 1),
            new_symbol=f"SYM_{i+1}",
        )
        for i in range(1600)
    ]
    resolved = resolve_symbol_lineage(Exchange.NSE, "SYM_0", date(2026, 6, 1), chain_actions)
    assert resolved == "SYM_1600"


def test_r7_replay_fixture_rejects_non_finite_values_and_constants() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        rec_nan_float = {
            "symbol": "INFY",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t0.isoformat(),
            "open": float("nan"),
            "high": "1510.00",
            "low": "1490.00",
            "close": "1505.00",
            "volume": 1000,
        }
        resp_nan_float = ProviderResponse(success=True, source="TEST", retrieval_timestamp=t0, records=(rec_nan_float,))
        with pytest.raises(FixtureIntegrityError, match="Non-finite float value"):
            save_replay_fixture(tmpdir, "fix_nan_fl", resp_nan_float, Exchange.NSE, "INFY", CandleInterval.M5)

        rec_inf_dec = {
            "symbol": "INFY",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t0.isoformat(),
            "open": Decimal("Infinity"),
            "high": Decimal("1510.00"),
            "low": Decimal("1490.00"),
            "close": Decimal("1505.00"),
            "volume": 1000,
        }
        resp_inf_dec = ProviderResponse(success=True, source="TEST", retrieval_timestamp=t0, records=(rec_inf_dec,))
        with pytest.raises(FixtureIntegrityError, match="Non-finite Decimal value"):
            save_replay_fixture(tmpdir, "fix_inf_dec", resp_inf_dec, Exchange.NSE, "INFY", CandleInterval.M5)

        valid_rec = {
            "symbol": "INFY",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t0.isoformat(),
            "open": "1500.00",
            "high": "1510.00",
            "low": "1490.00",
            "close": "1505.00",
            "volume": 1000,
        }
        resp_valid = ProviderResponse(success=True, source="TEST", retrieval_timestamp=t0, records=(valid_rec,))
        save_replay_fixture(tmpdir, "fix_valid", resp_valid, Exchange.NSE, "INFY", CandleInterval.M5)

        man_nan_path = Path(tmpdir) / "fix_man_nan.manifest.json"
        man_nan_path.write_text('{"fixture_id": NaN}', encoding="utf-8")
        pay_valid_path = Path(tmpdir) / "fix_man_nan.payload.json"
        pay_valid_path.write_text("[]", encoding="utf-8")
        p_man_nan = StoredReplayFixtureProvider(tmpdir, "fix_man_nan")
        with pytest.raises(FixtureIntegrityError, match="Non-finite JSON constant not allowed"):
            p_man_nan.fetch_historical(
                HistoricalDataRequest("INFY", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=5))
            )

        bad_payload = b'[{"symbol":"INFY","open":NaN}]'
        bad_digest = _compute_fixture_hmac(
            key_bytes=_DEFAULT_HMAC_KEY,
            fixture_id="fix_valid",
            source="TEST",
            exchange=Exchange.NSE.value,
            symbol="INFY",
            interval=CandleInterval.M5.value,
            recorded_at=t0.isoformat(),
            record_count=1,
            payload_bytes=bad_payload,
        )
        man_path = Path(tmpdir) / "fix_valid.manifest.json"
        import json
        man_data = json.loads(man_path.read_text(encoding="utf-8"))
        man_data["payload_sha256"] = bad_digest
        man_path.write_text(json.dumps(man_data), encoding="utf-8")

        pay_path = Path(tmpdir) / "fix_valid.payload.json"
        pay_path.write_bytes(bad_payload)
        provider = StoredReplayFixtureProvider(tmpdir, "fix_valid")
        with pytest.raises(FixtureIntegrityError, match="Non-finite JSON constant not allowed"):
            provider.fetch_historical(
                HistoricalDataRequest("INFY", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=5))
            )

