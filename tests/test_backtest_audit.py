"""Pruebas de la auditoría de la prueba histórica (Tarea 4 del Ciclo 3).

Todos los valores esperados se recalculan a mano en el propio test a partir de la
serie de precios guardada como fixture, sin reutilizar el código auditado.
"""

from __future__ import annotations

from pathlib import Path

from nexo_invest.backtest import BacktestConfig, audit_backtest, run_backtest
from nexo_invest.data.prices import series_from_fixture

FIXTURES = Path(__file__).parent / "fixtures"
YAHOO = FIXTURES / "yahoo_aapl_5y.json"

FEE = 0.0010
SLIPPAGE = 0.0005
CAPITAL = 1.0


def fixture_series():
    return series_from_fixture(YAHOO, symbol="AAPL")


def fixture_result():
    series = fixture_series()
    return run_backtest(series, BacktestConfig()), series


def test_auditoria_de_la_serie_real_no_detecta_errores():
    result, series = fixture_result()
    audit = audit_backtest(result, series)
    evaluated = [c for c in audit.checks if c.passed is not None]
    assert evaluated, "la auditoría no evaluó ninguna comprobación"
    assert all(c.passed for c in evaluated)
    assert audit.passed


def test_buy_hold_recalculado_a_mano_incluye_costes_de_entrada():
    result, series = fixture_result()
    first = series.adjusted_closes[0]
    last = series.adjusted_closes[-1]

    # Fórmula escrita a mano: se compran unidades con el capital inicial, pagando
    # deslizamiento en el precio de compra y comisión sobre el capital.
    units = (CAPITAL - CAPITAL * FEE) / (first * (1.0 + SLIPPAGE))
    expected = units * last - 1.0

    published = result.benchmark_full.total_return
    assert published is not None
    assert abs(published - expected) < 1e-12
    # La referencia con costes queda por debajo del precio puro: si no, los costes
    # se habrían quedado fuera de la comparación.
    raw = last / first - 1.0
    assert published < raw


def test_costes_de_entrada_afectan_a_ambas_curvas_por_igual():
    result, series = fixture_result()
    raw = series.adjusted_closes[-1] / series.adjusted_closes[0] - 1.0
    # La estrategia parte de capital inicial (sin costes todavía pagados en la
    # primera barra) y su curva sí descuenta los costes pagados posteriormente.
    assert result.strategy_full.total_return < raw
    assert result.benchmark_full.total_return < raw


def test_estrategia_no_supera_a_comprar_y_mantener_en_esta_serie():
    """Regresión del resultado publicado: la regla pierde frente al buy & hold."""

    result, _ = fixture_result()
    strategy = result.strategy_full.total_return
    hold = result.benchmark_full.total_return
    assert strategy is not None and hold is not None
    assert strategy < hold
    # Diferencia publicada en el informe (redondeada a 2 decimales).
    assert round(strategy * 100, 2) == 65.07
    assert round(hold * 100, 2) == 132.90


def test_rentabilidad_total_y_anualizada_recalculadas():
    result, _ = fixture_result()
    full = result.strategy_full
    total = result.equity_values[-1] / result.equity_values[0] - 1.0
    assert abs(full.total_return - total) < 1e-12
    annualized = (1.0 + total) ** (252 / full.sessions) - 1.0
    assert abs(full.annualized_return - annualized) < 1e-12


def test_auditoria_detecta_curva_manipulada():
    result, series = fixture_result()
    middle = len(result.equity_values) // 2
    result.equity_values[middle] = result.equity_values[middle] * 0.5

    audit = audit_backtest(result, series)
    failed = {c.name for c in audit.failed}
    # La rentabilidad total depende de los extremos y sigue cuadrando; lo que se
    # desajusta es la caída máxima, y la auditoría la detecta.
    assert "caída máxima de la estrategia" in failed
    assert not audit.passed


def test_auditoria_detecta_rentabilidad_falsificada():
    result, series = fixture_result()
    result.equity_values[-1] = result.equity_values[-1] * 1.5

    audit = audit_backtest(result, series)
    failed = {c.name for c in audit.failed}
    assert "rentabilidad total de la estrategia" in failed
    assert "rentabilidad anualizada" in failed


def test_auditoria_comprueba_ausencia_de_anticipacion():
    result, series = fixture_result()
    audit = audit_backtest(result, series)
    lookahead = [c for c in audit.checks if c.name == "ausencia de sesgo de anticipación"]
    assert lookahead, "falta la comprobación de anticipación"
    assert lookahead[0].passed is True
    assert "recortada" in lookahead[0].detail


def test_auditoria_declara_tratamiento_de_dividendos():
    result, series = fixture_result()
    audit = audit_backtest(result, series)
    dividend = [c for c in audit.checks if c.name == "tratamiento de dividendos"]
    assert dividend and dividend[0].passed is None
    assert "ajustados" in dividend[0].detail


def test_operaciones_reales_de_la_serie():
    result, _ = fixture_result()
    assert len(result.trades) == 3
    assert len(result.closed_trades) == 2
    dates = [t.entry_date for t in result.trades]
    assert dates == sorted(dates)
    assert any(t.exit_date is None for t in result.trades)  # posición abierta al final
