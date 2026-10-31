from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from nexo_invest.core.units import Frequency, Money, Period


@dataclass
class FiscalCalendar:
    """Calendario fiscal simple para identificar periodo fiscal y años fiscales.

    Un año fiscal se define por su mes de cierre (1-12). Si close_month es 12,
    el año fiscal coincide con el año civil; si es distinto, el año fiscal de una
    fecha de cierre se calcula con la regla estándar: si el mes de cierre es mayor
    que el mes de la fecha de cierre, el año fiscal es el año civil; si es menor o
    igual, el año fiscal es el año civil + 1 (cuando el cierre ya se ha alcanzado en
    ese año natural). Ver también fiscal_year_of_finish.
    """

    close_month: int  # 1..12

    def __post_init__(self) -> None:
        if not (1 <= self.close_month <= 12):
            raise ValueError(f"close_month debe estar entre 1 y 12, recibido {self.close_month}")

    def fiscal_year_of_period(self, period: Period) -> int:
        return self.fiscal_year_of_finish(period.end)

    def fiscal_year_of_finish(self, finish: date) -> int:
        """Año fiscal del periodo que termina en `finish`.

        Regla: el año fiscal de un periodo que termina en `finish` es el año fiscal
        cuyo mes de cierre es el primero en o después de finish.month dentro del ciclo
        annual. Equivalentemente: si finish.month <= close_month, el año fiscal es
        finish.year; si finish.month > close_month, el año fiscal es finish.year + 1.
        Convención: el año fiscal se nombra por el año civil del mes de cierre.
        Ejemplos con close_month=12:
          - diciembre 2024 (12 <= 12) => FY2024 (mes de cierre del año fiscal).
          - noviembre 2024 (11 <= 12) => FY2024.
          - enero 2025 (1 <= 12) => FY2025.
        Ejemplos con close_month=3:
          - febrero 2024 (2 <= 3) => FY2024 (año fiscal que termina en marzo 2024).
          - marzo 2024 (3 <= 3) => FY2024 (mes de cierre).
          - abril 2024 (4 > 3) => FY2025 (pertenece al año fiscal que termina en marzo 2025).
          - diciembre 2024 (12 > 3) => FY2025.
        """
        if finish.month <= self.close_month:
            return finish.year
        else:
            return finish.year + 1


    def is_same_fiscal_year(self, a: Period, b: Period) -> bool:
        return self.fiscal_year_of_finish(a.end) == self.fiscal_year_of_finish(b.end)

    def fiscal_year_end_for_year(self, fiscal_year: int) -> date:
        """Fecha de cierre del año fiscal dado, usando el último día del mes de cierre."""
        if self.close_month == 12:
            return date(fiscal_year, 12, 31)
        from calendar import monthrange
        _, last_day = monthrange(fiscal_year, self.close_month)
        return date(fiscal_year, self.close_month, last_day)


def growth_rate_strict(
    current: Optional[Money],
    prior: Optional[Money],
    *,
    same_scale_required: bool = True,
) -> Optional[float]:
    """Crecimiento estricto entre dos periodos del mismo tipo fiscal.

    Se comporta como growth_rate pero documenta que la comparación es punto a punto
    (no requiere calendario fiscal). Para crecimiento interanual estricto se debe usar
    con periodos de un año fiscal separado (ver same_fiscal_year_apart).
    """
    if current is None or prior is None:
        return None
    if prior.is_missing or current.is_missing:
        return None
    if prior.value == 0.0:
        return None
    if same_scale_required and current.scale is not prior.scale:
        return None
    return current.value / prior.value - 1.0


QUARTER_MIN_DAYS = 75
QUARTER_MAX_DAYS = 110


def _period_of(statement_or_period) -> Optional[Period]:
    """Obtiene el Period de un Period, un IncomeStatement o un BalanceSheet."""

    if isinstance(statement_or_period, Period):
        return statement_or_period
    inner = getattr(statement_or_period, "period", None)
    if isinstance(inner, Period):
        return inner
    return None


def is_quarterly_period(period: Optional[Period]) -> bool:
    """True solo si el periodo dura entre 75 y 110 días (un trimestre real).

    Sin esta comprobación un periodo anual podía colarse como si fuera un trimestre
    y el TTM sumaba cifras de duración distinta (error detectado con datos reales de
    Apple: el TTM resultante era aproximadamente anual + dos trimestres).
    """

    if period is None:
        return False
    days = (period.end - period.start).days
    return QUARTER_MIN_DAYS <= days <= QUARTER_MAX_DAYS


def ttm_periods(
    income_statements: Dict[date, Period],
    latest_end: date,
    calendar: Optional[FiscalCalendar] = None,
) -> List[date]:
    """Fechas de fin de los últimos 4 trimestres consecutivos que componen el TTM.

    Requisitos explícitos (todos obligatorios):

    1. El periodo más reciente no puede terminar después de `latest_end`.
    2. Cada periodo seleccionado debe ser trimestral de verdad (75-110 días).
    3. Entre el fin de un trimestre y el fin del siguiente debe haber 75-120 días.
    4. Los trimestres no pueden solaparse: el inicio del siguiente debe ser posterior
       al fin del anterior, con un hueco máximo de 5 días.

    Si no se cumplen los cuatro requisitos para cuatro trimestres, devuelve menos
    elementos (nunca más de 4) y el TTM no se calcula.
    """
    if not income_statements:
        return []

    periods = {end: _period_of(value) for end, value in income_statements.items()}
    ends = sorted(end for end, period in periods.items() if is_quarterly_period(period))
    if not ends:
        return []

    idx = len(ends) - 1
    while idx >= 0 and ends[idx] > latest_end:
        idx -= 1
    if idx < 0:
        return []

    selected: List[date] = [ends[idx]]
    while len(selected) < 4 and idx - 1 >= 0:
        candidate_end = ends[idx - 1]
        newer = periods[selected[0]]
        older = periods[candidate_end]
        if older is None or newer is None:
            break
        gap_between_ends = (newer.end - older.end).days
        if not (QUARTER_MIN_DAYS <= gap_between_ends <= 120):
            break
        if older.end >= newer.start:
            # Los periodos se solaparían: no son trimestres consecutivos distintos.
            idx -= 1
            break
        if (newer.start - older.end).days > 5:
            break
        selected.insert(0, candidate_end)
        idx -= 1
    return selected


def compute_ttm_from_quarters(
    income_statements: Dict[date, Period],
    values: Dict[date, Money],
    latest_end: date,
    calendar: Optional[FiscalCalendar] = None,
) -> Optional[Money]:
    """Calcula un valor TTM sumando los últimos 4 trimestres consecutivos.

    values: mapeo fecha_fin -> Money del componente a sumar (ej. revenue).
    Devuelve None si no hay suficientes trimestres consecutivos para TTM o algún
    valor es ausente.
    """
    quarters = ttm_periods(income_statements, latest_end, calendar)
    if len(quarters) < 4:
        return None
    acc = 0.0
    missing = False
    scale: Optional[Money] = None
    for q in quarters:
        v = values.get(q)
        if v is None or v.is_missing:
            missing = True
            continue
        if scale is None:
            scale = v
        else:
            if v.scale is not scale.scale:
                # intentar conversión a la escala del acumulador
                v = v.to_scale(scale.scale)
        acc += v.value
    if missing:
        return None
    if scale is None:
        return None
    return Money(acc, scale.currency, scale.scale, label="ttm")


def latest_fiscal_year_end_before(
    ends: List[date], latest_end: date, calendar: FiscalCalendar
) -> Optional[date]:
    """Fecha de fin del último periodo cuyo año fiscal es estrictamente anterior al año fiscal de latest_end."""
    if not ends:
        return None
    target_fy = calendar.fiscal_year_of_finish(latest_end)
    candidates: List[date] = []
    for e in ends:
        if calendar.fiscal_year_of_finish(e) < target_fy and e <= latest_end:
            candidates.append(e)
    if not candidates:
        return None
    return max(candidates)
