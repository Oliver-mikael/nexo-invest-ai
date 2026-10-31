"""Pruebas del adaptador de precios y de la prueba histórica (Hito 6).

Las series sintéticas se construyen con resultados calculables a mano. La serie real
está congelada en tests/fixtures/yahoo_aapl_5y.json (descarga del 2026-10-27), de modo
que ninguna prueba necesita red.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from nexo_invest.backtest import (
    BacktestConfig,
    _max_drawdown,
    _period_metrics,
    run_backtest,
)
from nexo_invest.core.sources import ProvenanceLevel
from nexo_invest.data.prices import (
    PriceSeries,
    PriceSourceError,
    parse_chart_payload,
    series_from_fixture,
)

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_aapl_5y.json"
START = date(2020, 1, 1)


def synthetic_series(daily_returns, *, lookback=None) -> PriceSeries:
    """Serie construida a partir de una lista de rentabilidades diarias."""

    dates = []
    closes = []
    price = 100.0
    day = START
    for index, ret in enumerate(daily_returns):
        closes.append(price)
        dates.append(day)
        day = day + timedelta(days=1) if day.weekday() < 4 else day + timedelta(days=3)
        price *= 1.0 + ret
    return PriceSeries(
        symbol="SYNT",
        currency="USD",
        dates=dates,
        adjusted_closes=list(closes),
        closes=list(closes),
        volumes=[1000.0] * len(closes),
    )


class TestPriceAdapter:
    @pytest.fixture(scope="class")
    @classmethod
    def apple_series(cls) -> PriceSeries:
        return series_from_fixture(FIXTURE, symbol="AAPL")

    def test_fixture_is_a_real_download_with_provenance(self, apple_series):
        assert apple_series.symbol == "AAPL"
        assert apple_series.currency == "USD"
        assert len(apple_series) > 1200
        assert apple_series.provenance_level is ProvenanceLevel.EXTERNAL_DOWNLOADED
        assert apple_series.source is not None
        assert apple_series.source.hash
        assert apple_series.source.url.startswith("file://")
        assert "no oficial" in " ".join(apple_series.limitations)

    def test_downloaded_data_is_never_marked_as_verified(self, apple_series):
        assert apple_series.provenance_level.usable_as_real_data is True
        assert apple_series.provenance_level is not ProvenanceLevel.EXTERNAL_VALIDATED

    def test_dates_are_ordered_and_unique(self, apple_series):
        assert apple_series.dates == sorted(apple_series.dates)
        assert len(set(apple_series.dates)) == len(apple_series.dates)

    def test_lookup_never_uses_future_data(self, apple_series):
        assert apple_series.value_at(date(2000, 1, 1)) is None
        middle = apple_series.dates[len(apple_series) // 2]
        index = apple_series.index_at_or_before(middle)
        assert apple_series.dates[index] <= middle
        assert apple_series.trading_days_before(apple_series.dates[10], 50) is None

    def test_parse_rejects_payloads_with_errors(self):
        with pytest.raises(PriceSourceError, match="error"):
            parse_chart_payload({"chart": {"error": {"code": "Not Found"}}})

    def test_parse_rejects_series_without_data(self):
        with pytest.raises(PriceSourceError, match="serie de precios"):
            parse_chart_payload({"chart": {"result": []}})

    def test_gaps_are_dropped_not_filled(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "X", "currency": "USD"},
                        "timestamp": [1, 2, 3],
                        "indicators": {
                            "quote": [{"close": [10.0, None, 12.0], "volume": [1, 2, 3]}],
                            "adjclose": [{"adjclose": [10.0, None, 12.0]}],
                        },
                    }
                ]
            }
        }
        series = parse_chart_payload(payload)
        assert len(series) == 2
        assert series.closes == [10.0, 12.0]


class TestBacktestWithoutLookAhead:
    def test_decisions_use_only_past_and_present_data(self):
        returns = [0.002 if i % 50 else -0.03 for i in range(120)]
        series = synthetic_series(returns)
        config = BacktestConfig(lookback_sessions=10, rebalance_every_sessions=3)
        full = run_backtest(series, config)

        cutoff = 60
        truncated = series.slice(end=series.dates[cutoff])
        partial = run_backtest(truncated, config)

        assert [t.entry_date for t in partial.trades] == [
            t.entry_date for t in full.trades if t.entry_date <= series.dates[cutoff]
        ]
        assert partial.equity_values == pytest.approx(
            full.equity_values[: cutoff + 1]
        )

    def test_no_position_before_the_first_decision(self):
        series = synthetic_series([0.01] * 40)
        result = run_backtest(
            series, BacktestConfig(lookback_sessions=10, rebalance_every_sessions=5)
        )
        first_decision = series.dates[10]
        assert all(
            trade.entry_date >= first_decision for trade in result.trades
        )


class TestBacktestResults:
    def test_constant_rise_stays_invested_without_drawdown(self):
        series = synthetic_series([0.01] * 60)
        result = run_backtest(
            series,
            BacktestConfig(
                lookback_sessions=5,
                rebalance_every_sessions=5,
                commission_per_trade=0.0,
                slippage=0.0,
            ),
        )
        assert result.strategy_full.max_drawdown == 0.0
        assert result.strategy_full.total_return > 0
        assert result.strategy_full.sessions_invested > 0
        assert len(result.trades) >= 1

    def test_slippage_produces_an_immediate_marked_loss(self):
        series = synthetic_series([0.01] * 60)
        result = run_backtest(
            series, BacktestConfig(lookback_sessions=5, rebalance_every_sessions=5)
        )
        # Comprar con deslizamiento deja la posición por debajo del efectivo inicial:
        # la caída máxima es pequeña pero no cero, y eso es el coste, no un error.
        assert -0.01 < result.strategy_full.max_drawdown < 0.0

    def test_constant_fall_stays_in_cash(self):
        series = synthetic_series([-0.01] * 40)
        result = run_backtest(
            series, BacktestConfig(lookback_sessions=5, rebalance_every_sessions=5)
        )
        assert result.strategy_full.sessions_invested == 0
        assert result.strategy_full.total_return == pytest.approx(0.0)
        assert result.trades == []

    def test_costs_reduce_the_result(self):
        returns = [0.01 if i % 3 else -0.004 for i in range(200)]
        series = synthetic_series(returns)
        cheap = run_backtest(
            series,
            BacktestConfig(lookback_sessions=5, rebalance_every_sessions=2, commission_per_trade=0.0, slippage=0.0),
        )
        expensive = run_backtest(
            series,
            BacktestConfig(lookback_sessions=5, rebalance_every_sessions=2, commission_per_trade=0.01, slippage=0.01),
        )
        assert expensive.strategy_full.total_return < cheap.strategy_full.total_return
        assert len(expensive.trades) == len(cheap.trades)

    def test_benchmark_matches_buy_and_hold_arithmetic(self):
        series = synthetic_series([0.01] * 30)
        config = BacktestConfig(lookback_sessions=5, commission_per_trade=0.0, slippage=0.0)
        result = run_backtest(series, config)
        expected = series.adjusted_closes[-1] / series.adjusted_closes[0] - 1.0
        assert result.benchmark_full.total_return == pytest.approx(expected)

    def test_dev_and_eval_splits_cover_the_series(self):
        series = synthetic_series([0.005] * 100)
        result = run_backtest(
            series, BacktestConfig(lookback_sessions=5, dev_fraction=0.6)
        )
        assert result.strategy_dev.first_date == series.dates[0]
        assert result.strategy_eval.last_date == series.dates[-1]
        # Cada tramo aporta (n-1) rentabilidades: el empalme descuenta una sesión por tramo.
        assert result.strategy_dev.sessions + result.strategy_eval.sessions == len(series) - 2

    def test_short_series_is_rejected(self):
        series = synthetic_series([0.01] * 20)
        with pytest.raises(ValueError, match="demasiado corta"):
            run_backtest(series, BacktestConfig(lookback_sessions=252))

    def test_invalid_parameters_are_rejected(self):
        with pytest.raises(ValueError):
            BacktestConfig(lookback_sessions=0)
        with pytest.raises(ValueError):
            BacktestConfig(slippage=0.5)
        with pytest.raises(ValueError):
            BacktestConfig(dev_fraction=0.95)


class TestMetricHelpers:
    def test_max_drawdown_on_known_curve(self):
        assert _max_drawdown([1.0, 1.2, 0.9, 1.0]) == pytest.approx(0.9 / 1.2 - 1.0)

    def test_max_drawdown_without_losses_is_zero(self):
        assert _max_drawdown([1.0, 1.1, 1.2]) == 0.0

    def test_volatility_of_constant_return_is_zero(self):
        values = [100.0 * (1.01**i) for i in range(30)]
        dates = [START + timedelta(days=i) for i in range(30)]
        metrics = _period_metrics("constante", values, dates, [True] * 30)
        assert metrics.annualized_volatility == pytest.approx(0.0, abs=1e-12)

    def test_annualization_uses_252_sessions(self):
        values = [100.0, 110.0]
        dates = [START, START + timedelta(days=1)]
        metrics = _period_metrics("dos sesiones", values, dates, [True, True])
        assert metrics.total_return == pytest.approx(0.1)
        assert metrics.annualized_return == pytest.approx(1.1**252 - 1.0)


class TestRealDataBacktest:
    @pytest.fixture(scope="class")
    @classmethod
    def result(cls):
        series = series_from_fixture(FIXTURE, symbol="AAPL")
        return run_backtest(series, BacktestConfig())

    def test_runs_on_five_years_of_real_prices(self, result):
        assert result.strategy_full.sessions > 1000
        assert result.benchmark_full.sessions == result.strategy_full.sessions

    def test_numbers_are_plausible(self, result):
        assert -1.0 < result.strategy_full.total_return < 10.0
        assert -1.0 <= result.strategy_full.max_drawdown <= 0.0
        assert result.strategy_full.annualized_volatility is not None
        assert 0.0 < result.strategy_full.annualized_volatility < 1.0

    def test_report_claims_nothing_about_profitability(self, result):
        text = result.markdown()
        assert "no demuestra que la estrategia sea rentable" in text
        assert "Sin sesgo de anticipación" in text
        assert "no oficial" in text

    def test_report_discloses_costs_and_split(self, result):
        text = result.markdown()
        assert "pb por operación" in text
        assert "desarrollo" in text and "evaluación" in text

    def test_trades_are_internally_consistent(self, result):
        for trade in result.closed_trades:
            assert trade.exit_date >= trade.entry_date
            assert trade.sessions_held is not None and trade.sessions_held >= 0
            assert trade.net_return is not None
