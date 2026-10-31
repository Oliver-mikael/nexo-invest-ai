from __future__ import annotations

import pytest
from datetime import date

from nexo_invest.core.sources import (
    DataSource,
    DataType,
    DataOrigin,
    Observation,
    ProvenanceRegistry,
    VerificationState,
    Scale,
)
from nexo_invest.core.units import Money, Period, Frequency
from nexo_invest.core.metrics import FinancialState, IncomeStatement, BalanceSheet
from nexo_invest.core.periods import FiscalCalendar


def simulated_source(entity: str = "Empresa X", metric: str = "income_statement") -> DataSource:
    return DataSource(
        id=f"simulated-{entity}-{metric}",
        name=f"Simulación interna — {entity}",
        entity=entity,
        data_type=DataType.INCOME_STATEMENT,
        origin=DataOrigin.SIMULATED,
        verification_state=VerificationState.VERIFIED,
        notes="Datos simulados de prueba. No son datos reales.",
        limitations=["No verificado en fuente externa.", "Usado solo para validación de cálculos."],
    )


def manual_source(entity: str = "Empresa X", metric: str = "income_statement") -> DataSource:
    return DataSource(
        id=f"manual-{entity}-{metric}",
        name=f"Introducido manualmente — {entity}",
        entity=entity,
        data_type=DataType.INCOME_STATEMENT,
        origin=DataOrigin.MANUAL,
        verification_state=VerificationState.PENDING,
        notes="Datos introducidos manualmente. Pendiente de verificación.",
    )


def external_unverified_source(entity: str) -> DataSource:
    return DataSource(
        id=f"ext-unverified-{entity}",
        name=f"Fuentes externas no verificadas — {entity}",
        entity=entity,
        data_type=DataType.INCOME_STATEMENT,
        origin=DataOrigin.EXTERNAL_UNVERIFIED,
        verification_state=VerificationState.UNVERIFIED,
        url="https://ejemplo.no/verificado",
        limitations=["No se ha extraído ni validado automáticamente.", "Requiere revisión humana."],
    )


def external_verified_source(entity: str) -> DataSource:
    return DataSource(
        id=f"ext-verified-{entity}",
        name=f"Fuentes externas verificadas — {entity}",
        entity=entity,
        data_type=DataType.INCOME_STATEMENT,
        origin=DataOrigin.EXTERNAL_VERIFIED,
        verification_state=VerificationState.VERIFIED,
        url="https://ejemplo.no/verificado",
        publication_date=date(2024, 12, 31),
        retrieval_date=date(2025, 3, 1),
        extraction_method="parse_manual_del_informe",
        notes="Verificado manualmente contra el informe público.",
        limitations=["Verificado por revisión humana, no por extracción automática."],
    )


@pytest.fixture
def registry() -> ProvenanceRegistry:
    return ProvenanceRegistry()


@pytest.fixture
def simulated_registry() -> ProvenanceRegistry:
    reg = ProvenanceRegistry()
    src = simulated_source()
    reg.register_source(src)
    return reg


def quarterly_periods(cal: FiscalCalendar, start_year: int, start_month: int, count: int):
    from dateutil.relativedelta import relativedelta
    try:
        from dateutil.relativedelta import relativedelta
        have_dateutil = True
    except Exception:
        have_dateutil = False

    periods = []
    month = start_month
    year = start_year
    for i in range(count):
        # cada trimestre dura 3 meses
        period_end_month = month + 2
        period_end_year = year
        if period_end_month > 12:
            period_end_month -= 12
            period_end_year += 1
        start_month_q = month
        start_year_q = year
        end_month = period_end_month
        end_year = period_end_year
        # usar ultimo dia del mes de cierre fiscal (alinear con cal.close_month)
        # simplificar: usar ultimo dia del mes de fin natural
        from calendar import monthrange
        _, last_day = monthrange(end_year, end_month)
        end = date(end_year, end_month, last_day)
        start = date(start_year_q, start_month_q, 1)
        freq = Frequency.QUARTERLY
        periods.append(Period(start=start, end=end, frequency=freq))
        month = end_month + 1
        if month > 12:
            month -= 12
            year += 1
    return periods


class TestDataSource:
    def test_basic(self):
        src = DataSource(
            id="s1",
            name="Fuente prueba",
            entity="Empresa X",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.SIMULATED,
            verification_state=VerificationState.VERIFIED,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        assert src.id == "s1"
        assert src.is_verified is True
        assert src.is_simulated is True
        assert src.is_manual is False
        assert src.is_external is False
        assert src.currency == "USD"
        assert src.scale is Scale.MILLIONS

    def test_minimal_required_fields(self):
        src = DataSource(id="s1", name="Fuente", entity="X")
        assert src.id == "s1"

    def test_required_fields_positive(self):
        src = DataSource(id="s1", name="Fuente", entity="X")
        assert src.id == "s1"
        assert src.name == "Fuente"
        assert src.entity == "X"
        assert src.is_manual is True
        assert src.is_verified is False

    def test_invalid_id(self):
        with pytest.raises(ValueError, match="DataSource.id"):
            DataSource(id="", name="n", entity="e")

    def test_invalid_entity(self):
        with pytest.raises(ValueError, match="DataSource.entity"):
            DataSource(id="s1", name="n", entity="")

    def test_invalid_name(self):
        with pytest.raises(ValueError, match="DataSource.name"):
            DataSource(id="s1", name="", entity="e")


class TestObservation:
    def test_basic(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120.0, "USD", Scale.MILLIONS)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.SIMULATED,
            verified=True,
        )
        assert obs.metric == "revenue"
        assert obs.value.value == pytest.approx(120.0)
        assert obs.value.scale is Scale.MILLIONS
        assert obs.is_verified is True
        assert obs.is_simulated is True
        assert obs.is_manual is False
        assert obs.is_external is False
        assert obs.is_missing is False

    def test_missing_value(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=None,
            value_origin=DataOrigin.SIMULATED,
        )
        assert obs.is_missing is True
        assert obs.is_verified is False

    def test_nan_value(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(float("nan"), "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        assert obs.is_missing is True
        assert obs.is_verified is False

    def test_unverified_source(self, registry):
        src = manual_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120.0, "USD", Scale.MILLIONS)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.MANUAL,
        )
        assert obs.is_verified is False
        assert obs.is_manual is True

    def test_external_unverified(self, registry):
        src = external_unverified_source("X")
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120.0, "USD", Scale.MILLIONS)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
        )
        assert obs.is_verified is False
        assert obs.is_external is True
        assert obs.is_manual is False
        assert obs.is_simulated is False
        assert obs.is_missing is False

    def test_external_verified(self, registry):
        src = external_verified_source("X")
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120.0, "USD", Scale.MILLIONS)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.EXTERNAL_VERIFIED,
            verified=True,
        )
        assert obs.is_verified is True
        assert obs.is_external is True
        assert obs.is_missing is False

    def test_scale_incompatible_value(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120000.0, "USD", Scale.UNITS)  # unidades
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.SIMULATED,
        )
        assert obs.value.value == pytest.approx(120000.0)
        assert obs.value.scale is Scale.UNITS
        assert obs.is_missing is False

    def test_different_currency_value(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        value = Money(120.0, "EUR", Scale.MILLIONS)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=value,
            value_origin=DataOrigin.SIMULATED,
        )
        assert obs.value.currency == "EUR"

    def test_duplicated_observation(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        with pytest.raises(ValueError, match="Observación duplicada"):
            registry.observation(
                source_id=src.id,
                metric="revenue",
                period=p,
                value=Money(125.0, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
            )


class TestProvenanceRegistry:
    def test_register_source(self, registry):
        src = simulated_source()
        registry.register_source(src)
        assert registry.sources[src.id] is src

    def test_register_source_duplicate(self, registry):
        src = simulated_source()
        registry.register_source(src)
        with pytest.raises(ValueError, match="Fuente duplicada"):
            registry.register_source(src)

    def test_register_observation(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        assert len(registry.observations) == 1
        assert obs.source.id == src.id

    def test_observation_for_metric_period(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        found = registry.observation_for_metric_period("revenue", date(2024, 3, 31))
        assert found is not None
        assert found.value.value == pytest.approx(120.0)

    def test_observation_for_metric_period_not_found(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        found = registry.observation_for_metric_period("revenue", date(2024, 6, 30))
        assert found is None

    def test_observations_for_metric(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p1 = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        p2 = Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY)
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p1,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p2,
            value=Money(125.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        found = registry.observations_for_metric("revenue")
        assert len(found) == 2

    def test_quality_report(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        report = registry.quality_report()
        assert "Observaciones totales: 1" in report
        # el source es VERIFIED pero la observacion no tiene verified=True por defecto -> cuenta como simulada sin verificar
        assert "Observaciones verificadas: 0" in report
        assert "Observaciones simuladas: 1" in report


class TestRegistryToFinancialState:
    def test_to_financial_state_from_observations(self, registry):
        src = simulated_source()
        registry.register_source(src)
        periods = [
            Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL),
            Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL),
        ]
        for p, rev in zip(periods, [100.0, 120.0]):
            registry.observation(
                source_id=src.id,
                metric="revenue",
                period=p,
                value=Money(rev, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
            )
        # convertir a FinancialState manualmente desde el registry
        state = FinancialState(company=src.entity, currency="USD")
        for obs in registry.observations.values():
            if obs.metric == "revenue":
                stmt = IncomeStatement(period=obs.period, revenue=obs.value)
                state.add_income_statement(stmt)
        from nexo_invest.core.metrics import FinancialMetrics
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.revenue.value == pytest.approx(120.0)
        assert m.revenue_growth == pytest.approx(0.20)

    def test_to_financial_state_with_ttm(self, registry):
        cal = FiscalCalendar(close_month=12)
        src = simulated_source()
        registry.register_source(src)
        periods = []
        months = [1, 4, 7, 10]
        base_year = 2024
        for i, m in enumerate(months):
            from calendar import monthrange
            end_month = m + 2 if m + 2 <= 12 else m + 2 - 12
            end_year = base_year if end_month >= m else base_year + 1
            if m == 10:
                end_month = 12
                end_year = 2024
            elif m == 7:
                end_month = 9
                end_year = 2024
            elif m == 4:
                end_month = 6
                end_year = 2024
            elif m == 1:
                end_month = 3
                end_year = 2024
            _, last_day = monthrange(end_year, end_month)
            start_month = m
            start_year = base_year
            p = Period(start=date(start_year, start_month, 1), end=date(end_year, end_month, last_day), frequency=Frequency.QUARTERLY)
            periods.append(p)
        revenues = [20.0, 22.0, 24.0, 26.0, 30.0]
        # agregar 5 periodos trimestrales consecutivos: Q4-2023, Q1-Q4-2024
        period_defs = [
            (date(2023, 10, 1), date(2023, 12, 31)),
            (date(2024, 1, 1), date(2024, 3, 31)),
            (date(2024, 4, 1), date(2024, 6, 30)),
            (date(2024, 7, 1), date(2024, 9, 30)),
            (date(2024, 10, 1), date(2024, 12, 31)),
        ]
        for (start, end), rev in zip(period_defs, revenues):
            p = Period(start=start, end=end, frequency=Frequency.QUARTERLY)
            registry.observation(
                source_id=src.id,
                metric="revenue",
                period=p,
                value=Money(rev, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
            )
        state = FinancialState(company=src.entity, currency="USD")
        for obs in registry.observations.values():
            if obs.metric == "revenue":
                stmt = IncomeStatement(period=obs.period, revenue=obs.value)
                state.add_income_statement(stmt)
        from nexo_invest.core.metrics import FinancialMetrics
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31), fiscal_calendar=cal)
        assert m.revenue_ttm is not None
        assert m.revenue_ttm.value == pytest.approx(102.0)
        assert m.revenue_ttm.scale is Scale.MILLIONS

    def test_source_with_incomplete_fields(self, registry):
        src = DataSource(id="s1", name="Fuente", entity="X")
        registry.register_source(src)
        assert src.url is None
        assert src.publication_date is None
        assert src.scale is None
        assert src.verification_state is VerificationState.UNVERIFIED
        assert src.origin is DataOrigin.MANUAL


class TestIntegrationFromProvenance:
    def test_metrics_from_simulated_sources(self):
        from nexo_invest.core.metrics import FinancialMetrics
        cal = FiscalCalendar(close_month=12)
        reg = ProvenanceRegistry()
        src = DataSource(
            id="sim-1",
            name="Simulación interna",
            entity="Empresa Y",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.SIMULATED,
            verification_state=VerificationState.VERIFIED,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        reg.register_source(src)
        periods = [
            Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL),
            Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL),
        ]
        for p, rev in zip(periods, [100.0, 120.0]):
            reg.observation(
                source_id=src.id,
                metric="revenue",
                period=p,
                value=Money(rev, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
                verified=True,
            )
        state = reg.to_financial_state(metric="revenue")
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31), fiscal_calendar=cal)
        assert m.revenue.value == pytest.approx(120.0)
        assert m.revenue_growth == pytest.approx(0.20)
        assert m.revenue_growth_fiscal == pytest.approx(0.20)

    def test_metrics_from_manual_sources_not_verified(self):
        from nexo_invest.core.metrics import FinancialMetrics
        reg = ProvenanceRegistry()
        src = DataSource(
            id="man-1",
            name="Introducido manualmente",
            entity="Empresa Z",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.MANUAL,
            verification_state=VerificationState.PENDING,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        reg.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
        reg.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.MANUAL,
            verified=False,
        )
        state = reg.to_financial_state(metric="revenue")
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.revenue.value == pytest.approx(120.0)
        assert m.notes["source_state"] == "computed_from_FinancialState"

    def test_ttm_from_simulated_sources(self):
        from nexo_invest.core.metrics import FinancialMetrics
        cal = FiscalCalendar(close_month=12)
        reg = ProvenanceRegistry()
        src = DataSource(
            id="sim-ttm",
            name="Simulación TTM",
            entity="Empresa TTM",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.SIMULATED,
            verification_state=VerificationState.VERIFIED,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        reg.register_source(src)
        period_defs = [
            (date(2023, 10, 1), date(2023, 12, 31)),
            (date(2024, 1, 1), date(2024, 3, 31)),
            (date(2024, 4, 1), date(2024, 6, 30)),
            (date(2024, 7, 1), date(2024, 9, 30)),
            (date(2024, 10, 1), date(2024, 12, 31)),
        ]
        revenues = [20.0, 22.0, 24.0, 26.0, 30.0]
        for (start, end), rev in zip(period_defs, revenues):
            p = Period(start=start, end=end, frequency=Frequency.QUARTERLY)
            reg.observation(
                source_id=src.id,
                metric="revenue",
                period=p,
                value=Money(rev, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
                verified=True,
            )
        state = reg.to_financial_state(metric="revenue")
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31), fiscal_calendar=cal)
        assert m.revenue_ttm is not None
        assert m.revenue_ttm.value == pytest.approx(102.0)
        assert m.revenue_ttm.scale is Scale.MILLIONS

    def test_to_financial_state_empty_registry(self):
        reg = ProvenanceRegistry()
        state = reg.to_financial_state(metric="revenue")
        assert state.company == ""
        assert state.currency == "USD"
        assert state.income_statements == {}


class TestDataValidationEdgeCases:
    def test_incompatible_currency_in_registry(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "EUR", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        # no se rechaza automaticamente, pero el dato queda registrado con moneda distinta
        assert obs.value.currency == "EUR"

    def test_missing_metric_rejected(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        with pytest.raises(ValueError, match="Observation.metric"):
            registry.observation(
                source_id=src.id,
                metric="",
                period=p,
                value=Money(120.0, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
            )

    def test_missing_source_rejected(self, registry):
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        with pytest.raises(KeyError, match="Fuente no registrada"):
            registry.observation(
                source_id="nonexistent",
                metric="revenue",
                period=p,
                value=Money(120.0, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.SIMULATED,
            )

    def test_period_future_end(self, registry):
        src = simulated_source()
        registry.register_source(src)
        p = Period(start=date(2025, 1, 1), end=date(2025, 3, 31), frequency=Frequency.QUARTERLY)
        obs = registry.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(120.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
        )
        assert obs.period.end == date(2025, 3, 31)
        assert obs.is_missing is False

class TestDataInsufficiencyInReport:
    def test_insufficient_data_no_investment_conclusion(self):
        from nexo_invest.core.report import AnalysisReport
        from nexo_invest.core.sources import DataSource, DataType, DataOrigin, VerificationState
        from nexo_invest.core.units import Money, Period, Frequency, Scale
        from datetime import date
        cal = FiscalCalendar(close_month=12)
        reg = ProvenanceRegistry()
        src = DataSource(
            id="s-insuf",
            name="Fuente con datos insuficientes",
            entity="Empresa X",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.MANUAL,
            verification_state=VerificationState.PENDING,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        reg.register_source(src)
        # registrar solo balance, sin ingresos -> revenue None
        p = Period(start=date(2024,1,1), end=date(2024,12,31), frequency=Frequency.ANNUAL)
        reg.observation(
            source_id=src.id,
            metric="total_debt",
            period=p,
            value=Money(80.0,"USD",Scale.MILLIONS),
            value_origin=DataOrigin.MANUAL,
            verified=False,
        )
        report = AnalysisReport.from_registry(
            registry=reg,
            company="Empresa X",
            analysis_date=date(2025,3,1),
            fiscal_calendar=cal,
        )
        md = report.markdown()
        assert report.metrics.revenue is None
        assert "Datos insuficientes para evaluar" in md
        assert "Cobertura:" in md
        assert "Ingresos TTM: no disponibles" in md
        assert "_Sin valoración calculada._" in md
        # asegurar que no hay lenguaje de recomendación injustificada
        forbidden = ["comprar", "vender", "recomendamos", "se recomienda", "inversión recomendada", "rentabilidad garantizada"]
        for w in forbidden:
            assert w.lower() not in md.lower(), f"conclusion injustificada detectada: {w}"
        assert "as" in md and "No constituye" in md and "asesoramiento financiero" in md
        # y que no se incluyó valoración ni conclusión de inversión
        assert "_Sin valoración calculada._" in md
        assert "## 9. Conclusión" in md
        assert "Datos insuficientes para evaluar" in md
        assert "Ingresos TTM: no disponibles" in md


class TestToFinancialStateRegression:
    """Regresión: to_financial_state debe incluir balance y flujo de caja.

    Antes existían dos definiciones del método y la segunda (solo ingresos)
    anulaba a la primera, por lo que balance y cash flow se perdían en silencio.
    """

    def _registry_with_full_statements(self):
        reg = ProvenanceRegistry()
        src = DataSource(
            id="s-reg",
            name="Fuente de regresión",
            entity="Empresa Regresión",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            verification_state=VerificationState.PENDING,
            currency="USD",
            scale=Scale.MILLIONS,
        )
        reg.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
        for metric, value in [
            ("revenue", 1000.0),
            ("total_debt", 300.0),
            ("cash_and_equivalents", 100.0),
            ("invested_capital", 800.0),
            ("free_cash_flow", 120.0),
            ("operating_cash_flow", 200.0),
            ("capital_expenditures", 80.0),
        ]:
            reg.observation(
                source_id=src.id,
                metric=metric,
                period=p,
                value=Money(value, "USD", Scale.MILLIONS),
                value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
            )
        return reg

    def test_balance_sheet_present_from_registry(self):
        reg = self._registry_with_full_statements()
        state = reg.to_financial_state()
        assert state.balance_sheets, "el balance debe llegar al FinancialState"
        bs = next(iter(state.balance_sheets.values()))
        assert bs.total_debt.value == pytest.approx(300.0)
        assert bs.cash_and_equivalents.value == pytest.approx(100.0)

    def test_cash_flow_present_from_registry(self):
        reg = self._registry_with_full_statements()
        state = reg.to_financial_state()
        assert state.cash_flows, "el flujo de caja debe llegar al FinancialState"
        cf = next(iter(state.cash_flows.values()))
        assert cf.free_cash_flow.value == pytest.approx(120.0)

    def test_metrics_from_registry_include_net_debt_and_fcf(self):
        from nexo_invest.core.metrics import FinancialMetrics
        reg = self._registry_with_full_statements()
        state = reg.to_financial_state()
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.net_debt is not None
        assert m.net_debt.value == pytest.approx(200.0)
        assert m.free_cash_flow is not None
        assert m.free_cash_flow.value == pytest.approx(120.0)
        assert m.return_on_invested_capital == pytest.approx(0.0) or m.return_on_invested_capital is None

    def test_metric_keyword_still_works(self):
        reg = self._registry_with_full_statements()
        state = reg.to_financial_state(metric="revenue")
        assert state.income_statements


class TestProvenanceLevels:
    def test_levels_are_distinct(self):
        from nexo_invest.core.sources import ProvenanceLevel
        assert ProvenanceLevel.LOCAL_FIXTURE is not ProvenanceLevel.SYNTHETIC
        assert ProvenanceLevel.SYNTHETIC is not ProvenanceLevel.EXTERNAL_DOWNLOADED
        assert ProvenanceLevel.EXTERNAL_DOWNLOADED.usable_as_real_data is True
        assert ProvenanceLevel.SYNTHETIC.usable_as_real_data is False
        assert ProvenanceLevel.LOCAL_FIXTURE.usable_as_real_data is False

    def test_simulated_never_becomes_external(self):
        from nexo_invest.core.sources import ProvenanceLevel
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        src = simulated_source()
        obs = Observation(
            source=src,
            period=p,
            metric="revenue",
            value=Money(10.0, "USD", Scale.MILLIONS),
            value_origin=DataOrigin.SIMULATED,
            verified=True,
        )
        assert obs.effective_provenance_level is ProvenanceLevel.SYNTHETIC
        assert obs.effective_provenance_level.usable_as_real_data is False

    def test_downloaded_is_not_corroborated(self):
        from nexo_invest.core.sources import ProvenanceLevel
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        src = DataSource(
            id="sec-1",
            name="SEC EDGAR companyfacts",
            entity="Example Inc",
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json",
            data_type=DataType.INCOME_STATEMENT,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            verification_state=VerificationState.PENDING,
            currency="USD",
            scale=Scale.UNITS,
        )
        obs = Observation(
            source=src,
            period=p,
            metric="revenue",
            value=Money(1.0, "USD", Scale.UNITS),
            value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
            verified=False,
        )
        assert obs.effective_provenance_level is ProvenanceLevel.EXTERNAL_DOWNLOADED
        assert obs.is_verified is False, "descargado no implica verificado"

    def test_level_counts_and_report(self):
        from nexo_invest.core.sources import ProvenanceLevel
        reg = ProvenanceRegistry()
        src = DataSource(
            id="sec-2",
            name="SEC EDGAR",
            entity="Example Inc",
            data_type=DataType.METRIC,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            verification_state=VerificationState.PENDING,
            currency="USD",
            scale=Scale.UNITS,
        )
        reg.register_source(src)
        p = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        reg.observation(
            source_id=src.id,
            metric="revenue",
            period=p,
            value=Money(1.0, "USD", Scale.UNITS),
            value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
            provenance_level=ProvenanceLevel.EXTERNAL_VALIDATED,
        )
        counts = reg.level_counts()
        assert counts[ProvenanceLevel.EXTERNAL_VALIDATED.value] == 1
        assert counts[ProvenanceLevel.SYNTHETIC.value] == 0
        report = reg.quality_report()
        assert "external_validated: 1" in report
        assert len(reg.real_data_observations()) == 1
