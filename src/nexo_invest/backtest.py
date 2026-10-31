"""Prueba histórica exploratoria de una regla de momento sobre precios reales.

Reglas de honestidad que este módulo aplica y no permite saltarse:

- **Sin sesgo de anticipación:** cada decisión de la sesión `i` usa solo precios con
  fecha `<= i`. La regla compara el cierre con el cierre de `lookback_sessions`
  sesiones antes; nunca lee datos posteriores.
- **Separación desarrollo/evaluación:** la serie se divide en un tramo de desarrollo y
  otro de evaluación. Los parámetros que aquí se usan están fijados de antemano
  (no se han optimizado sobre la muestra), y así se declara; aun así la separación se
  respeta y se informa de los dos tramos por separado.
- **Costes explícitos:** comisión por operación y deslizamiento, aplicados a cada
  cambio de estado. Sin costes, cualquier rotación parece mejor de lo que es.
- **Sin afirmaciones de rentabilidad:** el resultado se presenta como prueba
  exploratoria de un único activo y un único periodo. No es evidencia de que la
  estrategia funcione en el futuro ni en otros activos.
- **Sin atajos prohibidos:** no hay ventas en corto, ni apalancamiento, ni relleno de
  huecos, ni uso de información que no esté en la serie.

Una cartera personal no se simula aquí: cualquier seguimiento de posiciones exige
posiciones y transacciones reales del usuario (o una cartera declarada como simulada
por él), y este sistema no las inventa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from statistics import pstdev
from typing import List, Optional, Sequence

from nexo_invest.core.sources import ProvenanceLevel
from nexo_invest.data.prices import PriceSeries

SESSIONS_PER_YEAR = 252


@dataclass
class BacktestConfig:
    """Parámetros del experimento. Fijados de antemano, no optimizados."""

    label: str = "momento 12 meses, rebalanceo mensual"
    lookback_sessions: int = 252
    rebalance_every_sessions: int = 21
    commission_per_trade: float = 0.0010
    slippage: float = 0.0005
    dev_fraction: float = 0.6
    initial_capital: float = 1.0

    def __post_init__(self) -> None:
        if self.lookback_sessions < 1:
            raise ValueError("lookback_sessions debe ser al menos 1")
        if self.rebalance_every_sessions < 1:
            raise ValueError("rebalance_every_sessions debe ser al menos 1")
        if not 0 <= self.slippage < 0.05:
            raise ValueError("slippage debe estar entre 0 y 0.05 (5 %)")
        if not 0 <= self.commission_per_trade < 0.05:
            raise ValueError("commission_per_trade debe estar entre 0 y 0.05 (5 %)")
        if not 0.1 <= self.dev_fraction <= 0.9:
            raise ValueError("dev_fraction debe estar entre 0.1 y 0.9")


@dataclass
class Trade:
    entry_date: date
    entry_price: float
    entry_value: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    net_return: Optional[float] = None
    sessions_held: Optional[int] = None
    open: bool = True

    def close(self, exit_date: date, exit_price: float, proceeds: float, sessions: int) -> None:
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.net_return = proceeds / self.entry_value - 1.0
        self.sessions_held = sessions
        self.open = False


@dataclass
class PeriodMetrics:
    label: str
    sessions: int
    first_date: Optional[date]
    last_date: Optional[date]
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    annualized_volatility: Optional[float] = None
    max_drawdown: Optional[float] = None
    sessions_invested: int = 0
    invested_share: Optional[float] = None

    def markdown_row(self, name: str) -> str:
        def pct(value: Optional[float]) -> str:
            return "no calculable" if value is None else f"{value * 100:,.2f} %"

        return (
            f"| {name} | {self.sessions} | {pct(self.total_return)} | "
            f"{pct(self.annualized_return)} | {pct(self.annualized_volatility)} | "
            f"{pct(self.max_drawdown)} | {self.sessions_invested} |"
        )


@dataclass
class BacktestResult:
    symbol: str
    config: BacktestConfig
    trades: List[Trade] = field(default_factory=list)
    strategy_full: Optional[PeriodMetrics] = None
    strategy_dev: Optional[PeriodMetrics] = None
    strategy_eval: Optional[PeriodMetrics] = None
    benchmark_full: Optional[PeriodMetrics] = None
    benchmark_dev: Optional[PeriodMetrics] = None
    benchmark_eval: Optional[PeriodMetrics] = None
    equity_dates: List[date] = field(default_factory=list)
    equity_values: List[float] = field(default_factory=list)
    benchmark_values: List[float] = field(default_factory=list)
    provenance_level: ProvenanceLevel = ProvenanceLevel.EXTERNAL_DOWNLOADED
    source_url: Optional[str] = None
    data_limitations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def closed_trades(self) -> List[Trade]:
        return [t for t in self.trades if not t.open]

    def markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# Prueba histórica exploratoria — {self.symbol}")
        lines.append("")
        lines.append(f"**Regla evaluada:** {self.config.label}")
        lines.append("")
        lines.append(
            f"**Parámetros fijados antes de mirar los resultados:** sin optimización. "
            f"Ventana de {self.config.lookback_sessions} sesiones (≈ "
            f"{self.config.lookback_sessions / SESSIONS_PER_YEAR:.1f} años), rebalanceo cada "
            f"{self.config.rebalance_every_sessions} sesiones (≈ "
            f"{self.config.rebalance_every_sessions / 21:.1f} meses), comisión "
            f"{self.config.commission_per_trade * 10_000:.1f} pb por operación y "
            f"deslizamiento {self.config.slippage * 10_000:.1f} pb."
        )
        lines.append("")
        lines.append(f"**Fuente de precios:** {self.source_url or 'no registrada'}")
        lines.append("")
        lines.append(f"**Nivel de procedencia de los precios:** {self.provenance_level.value}")
        lines.append("")
        lines.append("## Metodología")
        lines.append("")
        lines.append(
            "- Sin sesgo de anticipación: cada decisión de la sesión `i` usa únicamente "
            "precios con fecha igual o anterior a `i`. No se lee ninguna observación "
            "posterior (hay una prueba automática que lo comprueba comparando la serie "
            "completa con la serie recortada)."
        )
        lines.append(
            "- La regla está invertida (mantiene el activo) cuando el cierre de la sesión "
            "supera el cierre de hace N sesiones, y en liquidez en caso contrario. La "
            "decisión se toma con datos de la propia sesión y se ejecuta a su cierre: "
            "supuesto declarado, no una ventaja."
        )
        lines.append(
            "- Sin ventas en corto, sin apalancamiento y sin relleno de huecos: las "
            "sesiones sin precio se descartan."
        )
        lines.append(
            "- El efectivo no remunera intereses. Los precios son ajustados por dividendos "
            "y desdoblamientos, y los huecos de negociación se descartan en lugar de rellenarse."
        )
        lines.append(
            "- Comparación con mantener el activo (buy & hold) desde la misma fecha inicial, "
            "con los mismos costes de entrada."
        )
        lines.append("")
        lines.append("## Resultados")
        lines.append("")
        lines.append("| Serie | Sesiones | Rentabilidad total | Anualizada | Volatilidad anualizada | Caída máxima | Sesiones invertido |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        if self.strategy_full:
            lines.append(self.strategy_full.markdown_row("Estrategia (periodo completo)"))
        if self.benchmark_full:
            lines.append(self.benchmark_full.markdown_row("Buy & hold (periodo completo)"))
        if self.strategy_dev:
            lines.append(self.strategy_dev.markdown_row("Estrategia (desarrollo)"))
        if self.benchmark_dev:
            lines.append(self.benchmark_dev.markdown_row("Buy & hold (desarrollo)"))
        if self.strategy_eval:
            lines.append(self.strategy_eval.markdown_row("Estrategia (evaluación)"))
        if self.benchmark_eval:
            lines.append(self.benchmark_eval.markdown_row("Buy & hold (evaluación)"))
        lines.append("")
        lines.append(
            f"Operaciones cerradas: {len(self.closed_trades)}. "
            f"Posición abierta al final: {'sí' if any(t.open for t in self.trades) else 'no'}."
        )
        lines.append("")
        if self.config.dev_fraction:
            lines.append(
                "La separación desarrollo/evaluación busca detectar el ajuste excesivo. "
                "Como los parámetros no se han optimizado sobre el tramo de desarrollo, esa "
                "separación aquí sirve de control de estabilidad, no de validación formal."
            )
            lines.append("")
        lines.append("## Limitaciones de esta prueba")
        lines.append("")
        for warning in self._standard_warnings():
            lines.append(f"- {warning}")
        for warning in self.warnings:
            lines.append(f"- {warning}")
        lines.append("")
        lines.append("## Procedencia y limitaciones de los datos")
        lines.append("")
        for limitation in self.data_limitations:
            lines.append(f"- {limitation}")
        lines.append("")
        lines.append(
            "**Conclusión:** esta prueba no demuestra que la estrategia sea rentable. "
            "Un solo activo, un solo periodo y una única regla no permiten afirmarlo; "
            "el resultado sirve para estudiar el comportamiento de la regla y sus costes, "
            "no para recomendarla."
        )
        return "\n".join(lines)

    def _standard_warnings(self) -> List[str]:
        return [
            "Un solo activo y un solo periodo: no hay evidencia de generalización.",
            "No se corrige por comparaciones múltiples: cambiar de activo o de periodo "
            "cambia el resultado.",
            "Los resultados son sensibles a la ventana elegida y a los costes aplicados.",
            "El periodo incluye el comportamiento concreto del mercado en esos años, que "
            "no tiene por qué repetirse.",
            "No se modelan impuestos, ni dividendos cobrados en efectivo (están dentro del "
            "precio ajustado), ni la liquidez real de las órdenes.",
        ]


@dataclass
class AuditCheck:
    """Una comprobación concreta de la prueba histórica."""

    name: str
    passed: Optional[bool]  # None: comprobación informativa, no evaluada
    detail: str

    @property
    def status(self) -> str:
        if self.passed is None:
            return "informativo"
        return "OK" if self.passed else "FALLO"


@dataclass
class BacktestAudit:
    checks: List[AuditCheck] = field(default_factory=list)

    @property
    def failed(self) -> List[AuditCheck]:
        return [c for c in self.checks if c.passed is False]

    @property
    def passed(self) -> bool:
        return not self.failed

    def markdown(self) -> str:
        lines = []
        for check in self.checks:
            lines.append(f"- **[{check.status}]** {check.name}: {check.detail}")
        return "\n".join(lines)


def audit_backtest(result: BacktestResult, series: PriceSeries) -> BacktestAudit:
    """Recalcula las cifras clave de la prueba con fórmulas independientes.

    No vuelve a ejecutar la estrategia para obtener los mismos números: los
    resultados publicados se recomputan desde la curva de patrimonio y desde la serie
    de precios con fórmulas escritas aparte, y se comprueba que no hubo anticipación
    repitiendo la ejecución sobre una serie recortada.
    """

    audit = BacktestAudit()
    full = result.strategy_full

    if full is None or not result.equity_values:
        audit.checks.append(
            AuditCheck("curva de patrimonio", False, "no hay curva que recalcular")
        )
        return audit

    # 1. Rentabilidad total recalculada desde los extremos de la curva.
    recomputed = result.equity_values[-1] / result.equity_values[0] - 1.0
    audit.checks.append(
        AuditCheck(
            "rentabilidad total de la estrategia",
            full.total_return is not None
            and abs(recomputed - full.total_return) < 1e-9,
            f"publicado {full.total_return if full.total_return is not None else 'None'} "
            f"vs recalculado {recomputed:.10f}",
        )
    )

    # 2. Rentabilidad anualizada recalculada desde la rentabilidad *recalculada* en el
    #    paso anterior (no desde la publicada: si alguien alterara la curva, esta
    #    comprobación tendría que saltar, no repetir el número viejo).
    if (1 + recomputed) > 0 and full.sessions > 0:
        recomputed_ann = (1 + recomputed) ** (SESSIONS_PER_YEAR / full.sessions) - 1.0
        ok = full.annualized_return is not None and abs(recomputed_ann - full.annualized_return) < 1e-9
    else:
        recomputed_ann, ok = None, False
    audit.checks.append(
        AuditCheck(
            "rentabilidad anualizada",
            ok,
            f"publicado {full.annualized_return} vs recalculado "
            f"{recomputed_ann if recomputed_ann is not None else 'None'}",
        )
    )

    # 3. Caída máxima: recorrido pico-a-mínimo recalculado a mano sobre la curva.
    peak = float("-inf")
    worst = 0.0
    for value in result.equity_values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    audit.checks.append(
        AuditCheck(
            "caída máxima de la estrategia",
            full.max_drawdown is not None and abs(worst - full.max_drawdown) < 1e-12,
            f"publicado {full.max_drawdown} vs recalculado {worst}",
        )
    )

    # 4. Buy & hold recalculado directamente desde los precios ajustados, incluyendo
    #    los mismos costes de entrada que la estrategia.
    if len(series.dates) >= 2:
        cfg = result.config
        entry_price = series.adjusted_closes[0] * (1.0 + cfg.slippage)
        fee = cfg.initial_capital * cfg.commission_per_trade
        units = (cfg.initial_capital - fee) / entry_price
        hold = units * series.adjusted_closes[-1] - 1.0
        bench = result.benchmark_full
        ok = bench is not None and bench.total_return is not None and abs(hold - bench.total_return) < 1e-9
        audit.checks.append(
            AuditCheck(
                "rentabilidad del buy & hold",
                ok,
                f"publicado {bench.total_return if bench and bench.total_return is not None else 'None'} "
                f"vs recalculado {hold:.10f}",
            )
        )

    # 5. Coherencia de las operaciones con la curva: toda entrada y salida es
    #    anterior o igual a la última sesión y los periodos están ordenados.
    ordered = all(
        t.exit_date is None or t.exit_date >= t.entry_date for t in result.trades
    )
    in_range = all(
        t.entry_date >= series.dates[0] and t.entry_date <= series.dates[-1]
        for t in result.trades
    )
    audit.checks.append(
        AuditCheck(
            "orden temporal de las operaciones",
            ordered and in_range,
            f"{len(result.trades)} operaciones, {len(result.closed_trades)} cerradas, "
            "todas dentro de la serie",
        )
    )

    # 6. Anticipación: se repite la ejecución sobre la serie recortada en la sesión de
    #    corte y se exige la misma curva hasta ese punto. Si la estrategia leyera datos
    #    futuros, las dos curvas divergirían.
    cutoff = len(series.dates) // 2
    if cutoff + 1 >= result.config.lookback_sessions + 10:
        truncated = series.slice(end=series.dates[cutoff])
        try:
            rerun = run_backtest(truncated, result.config)
            length = min(len(rerun.equity_values), len(result.equity_values))
            same = all(
                abs(a - b) < 1e-12
                for a, b in zip(rerun.equity_values, result.equity_values[:length])
            ) and rerun.equity_dates == result.equity_dates[:length]
            detail = (
                f"curva idéntica hasta {series.dates[cutoff]} con la serie recortada"
                if same
                else "la curva cambia al recortar la serie: hay información futura en uso"
            )
        except ValueError as exc:
            same, detail = False, f"no se pudo repetir la ejecución recortada: {exc}"
        audit.checks.append(AuditCheck("ausencia de sesgo de anticipación", same, detail))

    # 7. Tratamiento de dividendos (informativo): ambos precios son ajustados.
    audit.checks.append(
        AuditCheck(
            "tratamiento de dividendos",
            None,
            "ambas series usan precios ajustados por dividendos y desdoblamientos; "
            "el efectivo en liquidez no genera rendimiento (limitación declarada)",
        )
    )
    return audit


def _max_drawdown(values: Sequence[float]) -> Optional[float]:
    peak: Optional[float] = None
    worst = 0.0
    seen = False
    for value in values:
        if peak is None or value > peak:
            peak = value
        if peak and peak > 0:
            seen = True
            drawdown = value / peak - 1.0
            worst = min(worst, drawdown)
    return worst if seen else None


def _period_metrics(
    label: str,
    values: Sequence[float],
    dates: Sequence[date],
    invested_flags: Sequence[bool],
    start_value: Optional[float] = None,
) -> Optional[PeriodMetrics]:
    """Métricas de una ventana de la curva.

    `start_value` permite medir la ventana desde el capital inicial en lugar de desde
    el primer valor de la ventana. Es necesario para el buy & hold: su primer valor ya
    tiene descontados los costes de entrada, y medir desde ahí habría excluido esos
    costes de la comparación mientras la estrategia sí los incluye.
    """

    if len(values) < 2:
        return None
    if start_value is None:
        start_value = values[0]
    end_value = values[-1]
    sessions = len(values) - 1
    total_return = end_value / start_value - 1.0 if start_value else None
    annualized = None
    if total_return is not None and sessions > 0 and (1.0 + total_return) > 0:
        annualized = (1.0 + total_return) ** (SESSIONS_PER_YEAR / sessions) - 1.0
    returns = [
        values[i] / values[i - 1] - 1.0
        for i in range(1, len(values))
        if values[i - 1]
    ]
    volatility = pstdev(returns) * math.sqrt(SESSIONS_PER_YEAR) if len(returns) > 1 else None
    invested = sum(1 for flag in invested_flags if flag)
    return PeriodMetrics(
        label=label,
        sessions=sessions,
        first_date=dates[0],
        last_date=dates[-1],
        total_return=total_return,
        annualized_return=annualized,
        annualized_volatility=volatility,
        max_drawdown=_max_drawdown(values),
        sessions_invested=invested,
        invested_share=invested / sessions if sessions else None,
    )


def run_backtest(series: PriceSeries, config: Optional[BacktestConfig] = None) -> BacktestResult:
    """Ejecuta la prueba histórica de la regla sobre la serie indicada."""

    config = config or BacktestConfig()
    if len(series) < config.lookback_sessions + 10:
        raise ValueError(
            "Serie demasiado corta para la ventana elegida: hacen falta al menos "
            f"{config.lookback_sessions + 10} sesiones y hay {len(series)}"
        )

    prices = series.adjusted_closes
    dates = series.dates

    cash = config.initial_capital
    units = 0.0
    invested = False
    current_trade: Optional[Trade] = None
    entry_index: Optional[int] = None

    equity_values: List[float] = []
    invested_flags: List[bool] = []
    trades: List[Trade] = []

    for index, (day, price) in enumerate(zip(dates, prices)):
        decides_now = (
            index >= config.lookback_sessions
            and (index - config.lookback_sessions) % config.rebalance_every_sessions == 0
        )
        if decides_now:
            past_price = prices[index - config.lookback_sessions]
            want_invested = price > past_price
            if want_invested and not invested:
                buy_price = price * (1.0 + config.slippage)
                fee = cash * config.commission_per_trade
                units = (cash - fee) / buy_price
                current_trade = Trade(
                    entry_date=day,
                    entry_price=buy_price,
                    entry_value=cash,
                )
                trades.append(current_trade)
                entry_index = index
                cash = 0.0
                invested = True
            elif not want_invested and invested and current_trade is not None:
                sell_price = price * (1.0 - config.slippage)
                proceeds = units * sell_price * (1.0 - config.commission_per_trade)
                current_trade.close(
                    exit_date=day,
                    exit_price=sell_price,
                    proceeds=proceeds,
                    sessions=index - (entry_index or index),
                )
                cash = proceeds
                units = 0.0
                invested = False
                current_trade = None

        equity_values.append(cash + units * price)
        invested_flags.append(invested)

    # Posición todavía abierta al cierre de la serie: se informa como abierta.
    if current_trade is not None:
        last_price = prices[-1]
        current_trade.net_return = (
            (units * last_price) / current_trade.entry_value - 1.0
            if current_trade.entry_value
            else None
        )
        current_trade.sessions_held = len(prices) - 1 - (entry_index or 0)

    # Referencia buy & hold con los mismos costes de entrada y sin rotación.
    entry_price = prices[0] * (1.0 + config.slippage)
    fee = config.initial_capital * config.commission_per_trade
    benchmark_units = (config.initial_capital - fee) / entry_price if entry_price else 0.0
    benchmark_values = [benchmark_units * price for price in prices]

    result = BacktestResult(
        symbol=series.symbol,
        config=config,
        trades=trades,
        equity_dates=list(dates),
        equity_values=equity_values,
        benchmark_values=benchmark_values,
        provenance_level=series.provenance_level,
        source_url=series.source.url if series.source else None,
        data_limitations=list(series.limitations),
    )
    # Ambas curvas se miden desde el capital inicial para que los costes de entrada
    # entren en las dos por igual.
    result.strategy_full = _period_metrics(
        "full", equity_values, dates, invested_flags,
        start_value=config.initial_capital,
    )
    result.benchmark_full = _period_metrics(
        "full", benchmark_values, dates, [True] * len(dates),
        start_value=config.initial_capital,
    )

    split = int(len(prices) * config.dev_fraction)
    if split >= 2 and len(prices) - split >= 2:
        result.strategy_dev = _period_metrics(
            "dev", equity_values[:split], dates[:split], invested_flags[:split]
        )
        result.strategy_eval = _period_metrics(
            "eval", equity_values[split:], dates[split:], invested_flags[split:]
        )
        result.benchmark_dev = _period_metrics(
            "dev", benchmark_values[:split], dates[:split], [True] * split,
            start_value=config.initial_capital,
        )
        result.benchmark_eval = _period_metrics(
            "eval", benchmark_values[split:], dates[split:], [True] * (len(dates) - split)
        )
    return result
