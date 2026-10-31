from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from nexo_invest.core.units import Frequency, Money, Period, Scale
from nexo_invest.core.periods import (
    FiscalCalendar,
    growth_rate_strict,
    ttm_periods,
    compute_ttm_from_quarters,
    latest_fiscal_year_end_before,
)


@dataclass
class IncomeStatement:
    period: Period
    revenue: Optional[Money] = None
    gross_profit: Optional[Money] = None
    operating_income: Optional[Money] = None
    net_income: Optional[Money] = None
    ebitda: Optional[Money] = None
    interest_expense: Optional[Money] = None
    tax_provision: Optional[Money] = None
    depreciation_amortization: Optional[Money] = None
    income_before_tax: Optional[Money] = None
    shares_diluted: Optional[Money] = None


@dataclass
class BalanceSheet:
    period: Period
    total_assets: Optional[Money] = None
    total_liabilities: Optional[Money] = None
    total_equity: Optional[Money] = None
    total_debt: Optional[Money] = None
    cash_and_equivalents: Optional[Money] = None
    working_capital: Optional[Money] = None
    invested_capital: Optional[Money] = None
    shareholders_equity: Optional[Money] = None
    current_assets: Optional[Money] = None
    current_liabilities: Optional[Money] = None
    inventory: Optional[Money] = None
    short_term_investments: Optional[Money] = None
    long_term_debt_current: Optional[Money] = None
    long_term_debt_noncurrent: Optional[Money] = None
    short_term_borrowings: Optional[Money] = None
    notes: Dict[str, str] = field(default_factory=dict)


@dataclass
class CashFlow:
    period: Period
    operating_cash_flow: Optional[Money] = None
    capital_expenditures: Optional[Money] = None
    free_cash_flow: Optional[Money] = None
    dividends_paid: Optional[Money] = None
    share_repurchases: Optional[Money] = None
    capex_sign_convention: str = "capex positive"
    notes: Dict[str, str] = field(default_factory=dict)


@dataclass
class FinancialState:
    company: str
    currency: str
    statement_periods: List[Period] = field(default_factory=list)
    income_statements: Dict[date, IncomeStatement] = field(default_factory=dict)
    balance_sheets: Dict[date, BalanceSheet] = field(default_factory=dict)
    cash_flows: Dict[date, CashFlow] = field(default_factory=dict)

    def add_income_statement(self, stmt: IncomeStatement) -> None:
        self.income_statements[stmt.period.end] = stmt
        if stmt.period not in self.statement_periods:
            self.statement_periods.append(stmt.period)

    def add_balance_sheet(self, bs: BalanceSheet) -> None:
        self.balance_sheets[bs.period.end] = bs
        if bs.period not in self.statement_periods:
            self.statement_periods.append(bs.period)

    def add_cash_flow(self, cf: CashFlow) -> None:
        self.cash_flows[cf.period.end] = cf
        if cf.period not in self.statement_periods:
            self.statement_periods.append(cf.period)

    def from_provenance(cls, registry: "ProvenanceRegistry", metric: str = "revenue") -> "FinancialState":
        """Construye FinancialState a partir de las observaciones de un metrico registrado.

        Toma las observaciones de un métrico (ej. 'revenue') y las convierte en
        IncomeStatements en un FinancialState. Si hay datos ausentes o duplicados
        en el registro, este método los refleja (no los inventa).
        """
        if not registry.sources:
            return cls(company="", currency="USD")
        entity = next(iter(registry.sources.values())).entity
        currency = next(iter(registry.sources.values())).currency or "USD"
        state = cls(company=entity, currency=currency)
        for obs in registry.observations.values():
            if obs.metric == metric:
                stmt = IncomeStatement(period=obs.period, revenue=obs.value)
                state.add_income_statement(stmt)
        return state


def _missing(x: Optional[Money]) -> bool:
    return x is None or x.is_missing


def growth_rate(
    current: Optional[Money], prior: Optional[Money], *, same_scale_required: bool = True
) -> Optional[float]:
    """Crecimiento como cociente. None cuando no es calculable.

    Por defecto exige que ambos operandos tengan la misma escala, porque
    el crecimiento interanual y otros ratios comparativos pierden sentido si
    se mezclan escalas distintas sin transformación documentada.
    """
    if _missing(current) or _missing(prior) or prior.value == 0.0:
        return None
    if same_scale_required and current.scale is not prior.scale:
        return None
    return current.value / prior.value - 1.0


def margin(
    numerator: Optional[Money], denominator: Optional[Money], *, same_scale_required: bool = True
) -> Optional[float]:
    """Márgen como cociente. None si no es calculable.

    Por defecto exige escalas compatibles para evitar margenes
    incorrectos por mezcla de unidades.
    """
    if _missing(numerator) or _missing(denominator) or denominator.value == 0.0:
        return None
    if same_scale_required and numerator.scale is not denominator.scale:
        return None
    return numerator.value / denominator.value


@dataclass
class FinancialMetrics:
    company: str
    currency: str
    latest_period: Optional[Period] = None
    previous_period: Optional[Period] = None
    revenue: Optional[Money] = None
    previous_revenue: Optional[Money] = None
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    ebitda_margin: Optional[float] = None
    operating_income: Optional[Money] = None
    net_income: Optional[Money] = None
    ebitda: Optional[Money] = None
    free_cash_flow: Optional[Money] = None
    capital_expenditures: Optional[Money] = None
    operating_cash_flow: Optional[Money] = None
    total_debt: Optional[Money] = None
    cash_and_equivalents: Optional[Money] = None
    net_debt: Optional[Money] = None
    invested_capital: Optional[Money] = None
    return_on_invested_capital: Optional[float] = None
    revenue_ttm: Optional[Money] = None
    revenue_growth_fiscal: Optional[float] = None
    notes_fiscal: Dict[str, str] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)

    # Indicadores adicionales. Todos tienen fórmula explícita y quedan en None
    # cuando faltan los datos de entrada; ninguno se rellena con estimaciones mudas.
    current_assets: Optional[Money] = None
    current_liabilities: Optional[Money] = None
    inventory: Optional[Money] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    interest_expense: Optional[Money] = None
    interest_coverage: Optional[float] = None
    ebitda_reported: Optional[Money] = None
    ebitda_computed: Optional[Money] = None
    net_debt_to_ebitda: Optional[float] = None
    income_before_tax: Optional[Money] = None
    income_tax_expense: Optional[Money] = None
    effective_tax_rate: Optional[float] = None
    nopat: Optional[Money] = None
    roic_nopat: Optional[float] = None
    invested_capital_estimated: bool = False
    fcf_conversion_ocf: Optional[float] = None
    fcf_conversion_net_income: Optional[float] = None
    capex_to_revenue: Optional[float] = None
    shares_diluted: Optional[Money] = None
    shares_diluted_prior: Optional[Money] = None
    dilution_rate: Optional[float] = None
    cash_and_short_term_investments: Optional[Money] = None
    dividends_paid: Optional[Money] = None
    share_repurchases: Optional[Money] = None
    free_cash_flow_estimated: bool = False

    @classmethod
    def from_state(cls, state: FinancialState, latest_end: date, *, fiscal_calendar: Optional[FiscalCalendar] = None) -> "FinancialMetrics":
        """Construye métricas a partir de un FinancialState.

        Usa la fecha de fin del periodo más reciente disponible. Calcula solo lo
        que los datos permiten; los valores ausentes se dejan como None.
        """
        instance = cls(company=state.company, currency=state.currency)
        instance.notes["source_state"] = "computed_from_FinancialState"

        # Elegir periodo más reciente con ingresos si existe
        latest = instance._latest_period_with(state, latest_end)
        if latest is None:
            instance.notes["latest_period_missing"] = "sin ingresos reportados"
            return instance

        instance.latest_period = latest
        latest_stmt = state.income_statements.get(latest.end)

        instance.revenue = latest_stmt.revenue if latest_stmt else None

        # Periodo anterior para crecimiento (misma frecuencia)
        prev = instance._previous_period(state, latest.end, latest.frequency)
        instance.previous_period = prev
        prev_stmt = state.income_statements.get(prev.end) if prev else None

        instance.previous_revenue = prev_stmt.revenue if prev_stmt else None
        instance.revenue_growth = growth_rate(instance.revenue, instance.previous_revenue)

        instance.operating_income = latest_stmt.operating_income if latest_stmt else None
        instance.net_income = latest_stmt.net_income if latest_stmt else None
        instance.ebitda = latest_stmt.ebitda if latest_stmt else None

        instance.gross_margin = margin(
            latest_stmt.gross_profit if latest_stmt else None,
            instance.revenue,
        )
        instance.operating_margin = margin(
            instance.operating_income, instance.revenue
        )
        instance.net_margin = margin(instance.net_income, instance.revenue)
        instance.ebitda_margin = margin(instance.ebitda, instance.revenue)

        latest_cf = state.cash_flows.get(latest.end)
        instance.operating_cash_flow = latest_cf.operating_cash_flow if latest_cf else None
        instance.capital_expenditures = latest_cf.capital_expenditures if latest_cf else None
        instance.free_cash_flow = latest_cf.free_cash_flow if latest_cf else None

        # FCF: si la empresa no lo reporta, se estima como flujo operativo menos el
        # valor absoluto de las inversiones (capex). Es una estimación derivada de
        # hechos observados, no una cifra reportada, y así queda marcada.
        if (
            _missing(instance.free_cash_flow)
            and not _missing(instance.operating_cash_flow)
            and not _missing(instance.capital_expenditures)
        ):
            if instance.operating_cash_flow.scale is instance.capital_expenditures.scale:
                instance.free_cash_flow = Money(
                    instance.operating_cash_flow.value
                    - abs(instance.capital_expenditures.value),
                    currency=state.currency,
                    scale=instance.operating_cash_flow.scale,
                    label="free_cash_flow_estimado",
                )
                instance.free_cash_flow_estimated = True
                instance.notes["free_cash_flow"] = (
                    "estimado como flujo de caja operativo - valor absoluto de las "
                    "inversiones (la empresa no lo reporta como tal)"
                )
            else:
                instance.notes["free_cash_flow"] = (
                    "no calculable: flujo operativo e inversiones en escalas distintas"
                )

        latest_bs = state.balance_sheets.get(latest.end)
        instance._compute_debt(latest_bs, state)

        instance.return_on_invested_capital = None
        if (
            instance.invested_capital is not None
            and instance.invested_capital.value != 0.0
            and instance.operating_income is not None
        ):
            # ROIC aproximado como operating_income / invested_capital.
            # Esta es una simplificación: una definición más estricta usaría NOPAT
            # (operating income ajustado por impuestos) y invested capital promedio
            # o periodo. Se documenta como aproximación hasta disponer de esos datos.
            instance.return_on_invested_capital = (
                instance.operating_income.value / instance.invested_capital.value
            )
            instance.notes["roic_definition"] = (
                "operating_income / invested_capital (aproximación, no NOPAT)"
            )

        instance._compute_liquidity(latest_bs, state)
        instance._compute_coverage_and_nopat(latest_stmt, latest_bs, state)
        instance._compute_cash_quality(latest_stmt, latest_cf)
        instance._compute_dilution(latest_stmt, prev_stmt)

        if fiscal_calendar is not None:
            prev_fy_end = instance._previous_fiscal_year_end(state, latest_end, fiscal_calendar)
            if prev_fy_end is not None:
                prev_stmt = state.income_statements.get(prev_fy_end)
                prev_rev = prev_stmt.revenue if prev_stmt else None
                instance.previous_revenue = prev_rev
                instance.revenue_growth_fiscal = growth_rate_strict(instance.revenue, prev_rev)
                if instance.revenue_growth_fiscal is not None:
                    instance.revenue_growth = instance.revenue_growth_fiscal
                    instance.notes_fiscal["fiscal_year_over_year_growth"] = (
                        "crecimiento interanual estricto (mismo campo fiscal)"
                    )
            ttm_rev = instance._ttm_revenue(state, latest_end, fiscal_calendar)
            if ttm_rev is not None:
                instance.revenue_ttm = ttm_rev
                instance.notes_fiscal["ttm_revenue"] = "suma de ultimos 4 trimestres consecutivos"
            if instance.previous_period is None:
                instance.previous_period = (
                    state.income_statements.get(prev_fy_end).period
                    if prev_fy_end in state.income_statements
                    else None
                )

        return instance

    # -- indicadores adicionales ------------------------------------------------------

    def _compute_debt(self, latest_bs: Optional[BalanceSheet], state: FinancialState) -> None:
        """Deuda total, caja, deuda neta y capital invertido.

        - Si el balance reporta `total_debt`, se usa tal cual.
        - Si no, se suma lo que la empresa sí reporta por componentes
          (deuda a largo plazo corriente y no corriente, financiación a corto plazo).
          Si falta algún componente, la cifra se marca como mínimo y no como total:
          una suma parcial no es la deuda total de la empresa.
        - Deuda neta = deuda total - (caja y equivalentes + inversiones a corto plazo).
          Las inversiones a corto plazo se incluyen porque son activos líquidos
          equivalentes a caja y suelen ser materiales (Apple las reporta por separado).
          Si no existen, se usa solo la caja y queda anotado.
        """
        if latest_bs is None:
            return
        self.cash_and_equivalents = latest_bs.cash_and_equivalents
        self.invested_capital = latest_bs.invested_capital

        components = (
            ("deuda a largo plazo corriente", latest_bs.long_term_debt_current),
            ("deuda a largo plazo no corriente", latest_bs.long_term_debt_noncurrent),
            ("financiacion a corto plazo", latest_bs.short_term_borrowings),
        )
        total = latest_bs.total_debt
        if not _missing(total):
            self.total_debt = total
            if latest_bs.notes.get("total_debt"):
                self.notes["total_debt"] = latest_bs.notes["total_debt"]
        else:
            present = [(label, m) for label, m in components if not _missing(m)]
            if present:
                reference = present[0][1]
                if any(m.scale is not reference.scale for _, m in present):
                    self.notes["total_debt"] = (
                        "no calculable: componentes observados con escalas distintas"
                    )
                else:
                    value = sum(m.value for _, m in present)
                    self.total_debt = Money(
                        value,
                        currency=state.currency,
                        scale=reference.scale,
                        label="total_debt_desde_componentes",
                    )
                    absent = [label for label, m in components if _missing(m)]
                    note = "suma de componentes observados: " + ", ".join(
                        label for label, _ in present
                    )
                    if absent:
                        note += (
                            "; faltan " + ", ".join(absent)
                            + " (la cifra es un minimo, no la deuda total reportada)"
                        )
                    self.notes["total_debt"] = note
            else:
                self.notes["total_debt"] = (
                    "no calculable: ni deuda total ni componentes de deuda observados"
                )

        if _missing(self.total_debt):
            self.net_debt = None
            self.notes["net_debt"] = "no calculable: falta deuda total"
            return

        liquid = latest_bs.cash_and_equivalents
        sti = latest_bs.short_term_investments
        if _missing(liquid):
            self.net_debt = None
            self.notes["net_debt"] = "no calculable: falta caja y equivalentes"
            return
        components_used = "caja y equivalentes"
        liquid_value = liquid.value
        liquid_scale = liquid.scale
        if not _missing(sti):
            if sti.scale is not liquid_scale:
                sti = sti.to_scale(liquid_scale)
            liquid_value += sti.value
            components_used = "caja y equivalentes + inversiones a corto plazo"
        self.cash_and_short_term_investments = Money(
            liquid_value,
            currency=state.currency,
            scale=liquid_scale,
            label="cash_and_short_term_investments",
        )
        self.net_debt = Money(
            self.total_debt.value - liquid_value,
            currency=state.currency,
            scale=self.total_debt.scale,
            label="net_debt",
        )
        note = f"deuda total - ({components_used})"
        if _missing(sti):
            note += "; inversiones a corto plazo no disponibles (no se asumen cero)"
        else:
            note += (
                "; no se restan inversiones a largo plazo, que tambien son activos "
                "liquidos pero no se reportan siempre: la deuda neta puede quedar "
                "sobrestimada"
            )
        self.notes["net_debt"] = note

    def _compute_liquidity(self, latest_bs: Optional[BalanceSheet], state: FinancialState) -> None:
        """Liquidez inmediata.

        - current_ratio = activo corriente / pasivo corriente
        - quick_ratio   = (activo corriente - inventario) / pasivo corriente

        Si falta el inventario, el quick ratio queda en None: se prefiere no calcularlo
        antes que suponer un inventario de cero.
        """
        if latest_bs is None:
            return
        self.current_assets = latest_bs.current_assets
        self.current_liabilities = latest_bs.current_liabilities
        self.inventory = latest_bs.inventory
        if _missing(self.current_assets) or _missing(self.current_liabilities):
            return
        if self.current_liabilities.value == 0.0:
            self.notes["current_ratio"] = "no calculable: pasivo corriente igual a cero"
            return
        self.current_ratio = self.current_assets.value / self.current_liabilities.value
        self.notes["current_ratio"] = "activo corriente / pasivo corriente"
        if _missing(self.inventory):
            self.notes["quick_ratio"] = "no calculable: inventario ausente (no se asume cero)"
            return
        self.quick_ratio = (
            self.current_assets.value - self.inventory.value
        ) / self.current_liabilities.value
        self.notes["quick_ratio"] = "(activo corriente - inventario) / pasivo corriente"

    def _compute_coverage_and_nopat(
        self,
        latest_stmt: Optional[IncomeStatement],
        latest_bs: Optional[BalanceSheet],
        state: FinancialState,
    ) -> None:
        """Cobertura de intereses, EBITDA y ROIC con NOPAT.

        - interest_coverage = resultado operativo / |gasto financiero|
        - ebitda_computed   = resultado operativo + depreciación y amortización
        - net_debt_to_ebitda = deuda neta / EBITDA (reportado si existe, si no calculado)
        - effective_tax_rate = impuestos / resultado antes de impuestos (acotado a [0, 1])
        - nopat = resultado operativo x (1 - tasa efectiva)
        - roic_nopat = NOPAT / capital invertido; si la empresa no reporta capital
          invertido se estima como deuda total + patrimonio y se marca la estimación.
        """
        if latest_stmt is None:
            return
        self.interest_expense = latest_stmt.interest_expense
        if not _missing(self.operating_income) and not _missing(self.interest_expense):
            if self.interest_expense.value != 0.0:
                self.interest_coverage = self.operating_income.value / abs(
                    self.interest_expense.value
                )
                self.notes["interest_coverage"] = (
                    "resultado operativo / valor absoluto del gasto financiero"
                )

        self.ebitda_reported = latest_stmt.ebitda
        da = latest_stmt.depreciation_amortization
        if not _missing(self.operating_income) and not _missing(da):
            self.ebitda_computed = Money(
                self.operating_income.value + da.value,
                currency=state.currency,
                scale=self.operating_income.scale,
                label="ebitda_calculado",
            )
            self.notes["ebitda_computed"] = (
                "resultado operativo + depreciación y amortización"
            )
        ebitda_for_ratio = self.ebitda_reported or self.ebitda_computed
        if not _missing(self.net_debt) and ebitda_for_ratio and ebitda_for_ratio.value:
            self.net_debt_to_ebitda = self.net_debt.value / ebitda_for_ratio.value
            self.notes["net_debt_to_ebitda"] = (
                "deuda neta / EBITDA reportado"
                if self.ebitda_reported
                else "deuda neta / EBITDA calculado"
            )

        self.income_before_tax = latest_stmt.income_before_tax
        self.income_tax_expense = latest_stmt.tax_provision
        if not _missing(self.income_before_tax) and not _missing(self.income_tax_expense):
            if self.income_before_tax.value > 0:
                rate = self.income_tax_expense.value / self.income_before_tax.value
                self.effective_tax_rate = min(max(rate, 0.0), 1.0)
                self.notes["effective_tax_rate"] = (
                    "impuestos / resultado antes de impuestos (acotado a [0, 1])"
                )
            else:
                self.notes["effective_tax_rate"] = (
                    "no calculable: resultado antes de impuestos no positivo"
                )

        if not _missing(self.operating_income) and self.effective_tax_rate is not None:
            nopat_value = self.operating_income.value * (1.0 - self.effective_tax_rate)
            self.nopat = Money(
                nopat_value,
                currency=state.currency,
                scale=self.operating_income.scale,
                label="nopat",
            )
            self.notes["nopat"] = "resultado operativo x (1 - tasa impositiva efectiva)"
            capital = self.invested_capital
            if (
                capital is None
                and self.total_debt is not None
                and latest_bs is not None
                and latest_bs.shareholders_equity is not None
                and self.total_debt.scale is latest_bs.shareholders_equity.scale
            ):
                capital = Money(
                    self.total_debt.value + latest_bs.shareholders_equity.value,
                    currency=state.currency,
                    scale=self.total_debt.scale,
                    label="invested_capital_estimado",
                )
                self.invested_capital = capital
                self.invested_capital_estimated = True
                self.notes["invested_capital"] = (
                    "estimado como deuda total + patrimonio (la empresa no lo reporta)"
                )
            if capital is not None and capital.value:
                self.roic_nopat = nopat_value / capital.value
                self.notes["roic_nopat"] = "NOPAT / capital invertido"

    def _compute_cash_quality(
        self,
        latest_stmt: Optional[IncomeStatement],
        latest_cf: Optional[CashFlow],
    ) -> None:
        """Calidad del beneficio: cuánto de las ganancias se convierte en caja.

        - fcf_conversion_ocf = FCF / flujo de caja operativo
        - fcf_conversion_net_income = FCF / resultado neto
        - capex_to_revenue = |inversiones| / ingresos
        """
        if latest_cf is not None:
            self.dividends_paid = latest_cf.dividends_paid
            self.share_repurchases = latest_cf.share_repurchases
        if not _missing(self.free_cash_flow) and not _missing(self.operating_cash_flow):
            if self.operating_cash_flow.value != 0.0:
                self.fcf_conversion_ocf = (
                    self.free_cash_flow.value / self.operating_cash_flow.value
                )
                self.notes["fcf_conversion_ocf"] = "FCF / flujo de caja operativo"
        if not _missing(self.free_cash_flow) and not _missing(self.net_income):
            if self.net_income.value != 0.0:
                self.fcf_conversion_net_income = (
                    self.free_cash_flow.value / self.net_income.value
                )
                self.notes["fcf_conversion_net_income"] = "FCF / resultado neto"
        if not _missing(self.capital_expenditures) and not _missing(self.revenue):
            if self.revenue.value != 0.0:
                self.capex_to_revenue = (
                    abs(self.capital_expenditures.value) / self.revenue.value
                )
                self.notes["capex_to_revenue"] = (
                    "valor absoluto de inversiones / ingresos (capex positivo en la fuente)"
                )

    def _compute_dilution(
        self,
        latest_stmt: Optional[IncomeStatement],
        prev_stmt: Optional[IncomeStatement],
    ) -> None:
        """Dilución con acciones diluidas medias del periodo y del periodo anterior.

        dilution_rate = acciones diluidas actuales / anteriores - 1

        El periodo anterior debe ser de la misma frecuencia. Comparar las acciones
        medias de un ejercicio anual con las de un trimestre mide mezcla de periodos,
        no dilución, así que en ese caso no se calcula nada.
        """
        if latest_stmt is None:
            return
        self.shares_diluted = latest_stmt.shares_diluted
        if prev_stmt is not None:
            if prev_stmt.period.frequency is not latest_stmt.period.frequency:
                self.notes["dilution_rate"] = (
                    "no calculable: el periodo anterior es de frecuencia distinta "
                    f"({prev_stmt.period.frequency.value} vs "
                    f"{latest_stmt.period.frequency.value})"
                )
                return
            self.shares_diluted_prior = prev_stmt.shares_diluted
        if _missing(self.shares_diluted) or _missing(self.shares_diluted_prior):
            if not _missing(self.shares_diluted):
                self.notes["dilution_rate"] = (
                    "no calculable: falta el periodo anterior comparable "
                    "(misma frecuencia y con acciones diluidas reportadas)"
                )
            return
        if self.shares_diluted_prior.value == 0.0:
            return
        self.dilution_rate = (
            self.shares_diluted.value / self.shares_diluted_prior.value - 1.0
        )
        self.notes["dilution_rate"] = (
            "acciones diluidas actuales / acciones diluidas del periodo anterior - 1"
        )

    def _latest_period_with(self, state: FinancialState, latest_end: date) -> Optional[Period]:
        if state.income_statements:
            for end in sorted(state.income_statements.keys(), reverse=True):
                if end <= latest_end:
                    return state.income_statements[end].period
        return None

    def _previous_fiscal_year_end(
        self, state: FinancialState, latest_end: date, calendar: FiscalCalendar
    ) -> Optional[date]:
        """Fecha de fin del ultimo periodo cuyo año fiscal es estrictamente anterior al año fiscal de latest_end."""
        ends = sorted(state.income_statements.keys())
        target_fy = calendar.fiscal_year_of_finish(latest_end)
        candidates: List[date] = []
        for e in ends:
            if calendar.fiscal_year_of_finish(e) < target_fy and e <= latest_end:
                candidates.append(e)
        if not candidates:
            return None
        return max(candidates)

    def _ttm_revenue(
        self, state: FinancialState, latest_end: date, calendar: Optional[FiscalCalendar] = None
    ) -> Optional[Money]:
        """Ingresos TTM sumando los últimos 4 trimestres consecutivos."""
        quarters = ttm_periods(state.income_statements, latest_end, calendar)
        if len(quarters) < 4:
            return None
        acc = 0.0
        scale: Optional[Money] = None
        missing = False
        for q in quarters:
            stmt = state.income_statements.get(q)
            if stmt is None or stmt.revenue is None or stmt.revenue.is_missing:
                missing = True
                continue
            v = stmt.revenue
            if scale is None:
                scale = v
            else:
                if v.scale is not scale.scale:
                    v = v.to_scale(scale.scale)
            acc += v.value
        if missing:
            return None
        if scale is None:
            return None
        return Money(acc, scale.currency, scale.scale, label="ttm")
    def _previous_period(
        self,
        state: FinancialState,
        current_end: date,
        frequency: Optional[Frequency] = None,
    ) -> Optional[Period]:
        """Periodo anterior comparable para crecimiento y dilución.

        Solo se consideran **estados de resultados**, no el conjunto de
        `statement_periods`, que también contiene periodos de balance y de flujo de
        caja. Los balances instantáneos se etiquetan como anuales, así que mirar esa
        lista devolvía un balance trimestral como si fuera el ejercicio anterior
        (defecto detectado con datos reales de Apple).

        Además se exige la misma frecuencia: comparar un ejercicio anual contra un
        trimestre es una comparación inválida.
        """
        statements = [
            stmt
            for end, stmt in state.income_statements.items()
            if stmt.period.end < current_end
            and (frequency is None or stmt.period.frequency is frequency)
        ]
        if not statements:
            return None
        return max(statements, key=lambda s: s.period.end).period



def summarize(metrics: FinancialMetrics) -> str:
    lines: List[str] = []
    lines.append(f"Empresa: {metrics.company} ({metrics.currency})")
    if metrics.latest_period:
        lines.append(
            f"Periodo: {metrics.latest_period.start} a {metrics.latest_period.end} "
            f"({metrics.latest_period.frequency.value})"
        )
    if metrics.revenue:
        lines.append(f"Ingresos: {metrics.revenue.value} {metrics.currency}")
    if metrics.revenue_growth is not None:
        lines.append(f"Crecimiento interanual: {metrics.revenue_growth:.2%}")
    else:
        lines.append("Crecimiento interanual: no calculable")
    if metrics.gross_margin is not None:
        lines.append(f"Márgen bruto: {metrics.gross_margin:.2%}")
    else:
        lines.append("Márgen bruto: no disponible")
    if metrics.operating_margin is not None:
        lines.append(f"Márgen operativo: {metrics.operating_margin:.2%}")
    else:
        lines.append("Márgen operativo: no disponible")
    if metrics.net_margin is not None:
        lines.append(f"Márgen neto: {metrics.net_margin:.2%}")
    else:
        lines.append("Márgen neto: no disponible")
    if metrics.ebitda_margin is not None:
        lines.append(f"Márgen EBITDA: {metrics.ebitda_margin:.2%}")
    else:
        lines.append("Márgen EBITDA: no disponible")
    if metrics.free_cash_flow:
        lines.append(f"FCF: {metrics.free_cash_flow.value} {metrics.currency}")
    if metrics.net_debt:
        lines.append(f"Deuda neta: {metrics.net_debt.value} {metrics.currency}")
    if metrics.return_on_invested_capital is not None:
        lines.append(f"ROIC: {metrics.return_on_invested_capital:.2%}")
    else:
        lines.append("ROIC: no disponible")
    if metrics.notes:
        lines.append("Notas:")
        for k, v in metrics.notes.items():
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)
