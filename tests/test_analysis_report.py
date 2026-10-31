"""Pruebas del informe sobre datos reales (Hito 4).

Todas las pruebas usan fixtures locales: ninguna hace peticiones de red. Los datos
reales de Apple provienen del documento companyfacts descargado de SEC EDGAR y
recortado a los conceptos usados; el fixture está identificado como tal en
tests/fixtures/README.md.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from nexo_invest.analysis import build_real_report
from nexo_invest.core.periods import FiscalCalendar
from nexo_invest.core.sources import (
    DataOrigin,
    DataSource,
    DataType,
    ProvenanceLevel,
    ProvenanceRegistry,
    VerificationState,
)
from nexo_invest.core.units import Frequency, Money, Period, Scale
from nexo_invest.data.sec_edgar import (
    SecEdgarResult,
    build_registry_from_companyfacts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sec_companyfacts_aapl_subset.json"
GENERATED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

ANNUAL_2023 = Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL)
ANNUAL_2024 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)


def _apple_result() -> SecEdgarResult:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return build_registry_from_companyfacts(payload, cik=320193, fetch_records=[])


def _simulated_result() -> SecEdgarResult:
    """Registro explícitamente simulado: no representa ninguna empresa real."""

    registry = ProvenanceRegistry()
    source = DataSource(
        id="fixture-simulado-1",
        name="Fixture local de pruebas",
        entity="Empresa Simulada S.A.",
        url="file://tests/fixtures/simulated.json",
        data_type=DataType.INCOME_STATEMENT,
        retrieval_date=date(2026, 1, 1),
        currency="USD",
        scale=Scale.UNITS,
        extraction_method="fixture construido a mano para pruebas",
        verification_state=VerificationState.UNVERIFIED,
        origin=DataOrigin.SIMULATED,
        notes="Dato simulado: no es información financiera real.",
    )
    registry.register_source(source)

    def obs(metric: str, period: Period, value: float) -> None:
        registry.observation(
            source_id=source.id,
            metric=metric,
            period=period,
            value=Money(value, "USD", Scale.UNITS),
            value_origin=DataOrigin.SIMULATED,
            provenance_level=ProvenanceLevel.LOCAL_FIXTURE,
        )

    obs("revenue", ANNUAL_2023, 900.0)
    obs("revenue", ANNUAL_2024, 1000.0)
    obs("gross_profit", ANNUAL_2024, 400.0)
    obs("operating_income", ANNUAL_2024, 200.0)
    obs("net_income", ANNUAL_2024, 120.0)
    obs("income_before_tax", ANNUAL_2024, 150.0)
    obs("income_tax_expense", ANNUAL_2024, 30.0)
    obs("operating_cash_flow", ANNUAL_2024, 250.0)
    obs("capital_expenditures", ANNUAL_2024, 50.0)
    obs("shareholders_equity", ANNUAL_2024, 800.0)
    obs("long_term_debt_noncurrent", ANNUAL_2024, 500.0)
    obs("cash_and_equivalents", ANNUAL_2024, 150.0)
    obs("shares_outstanding", ANNUAL_2024, 100.0)

    return SecEdgarResult(
        cik=1,
        entity_name="Empresa Simulada S.A.",
        registry=registry,
        facts={},
        fetch_records=[],
    )


@pytest.fixture(scope="module")
def apple_report():
    return build_real_report(_apple_result(), generated_at=GENERATED_AT)


@pytest.fixture(scope="module")
def apple_markdown(apple_report) -> str:
    return apple_report.markdown()


@pytest.fixture(scope="module")
def simulated_report():
    return build_real_report(_simulated_result(), generated_at=GENERATED_AT)


class TestReportStructure:
    def test_all_sections_present(self, apple_markdown):
        for heading in (
            "## 0. Cómo leer este informe",
            "## 1. Identidad y procedencia de la consulta",
            "## 2. Estado de calidad de los datos",
            "## 3. Hechos con fuente y periodo identificables",
            "## 4. Datos descargados que no se usan en conclusiones",
            "## 5. Información ausente o insuficiente",
            "## 6. Indicadores fundamentales: fórmula y requisito de datos",
            "## 7. Valoración por escenarios",
            "## 8. Riesgos y condiciones que invalidarían la tesis",
            "## 9. Datos simulados",
            "## 10. Limitaciones",
            "## 11. Trazabilidad",
            "## 12. Conclusión provisional",
        ):
            assert heading in apple_markdown

    def test_states_the_base_period_and_frequency(self, apple_markdown):
        assert "Periodo base de los indicadores:" in apple_markdown
        assert "**annual**" in apple_markdown

    def test_identifies_source_and_company(self, apple_markdown):
        assert "Apple Inc." in apple_markdown
        assert "320193" in apple_markdown
        assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json" in apple_markdown

    def test_declares_no_recommendation(self, apple_markdown):
        assert "No se emite recomendación de inversión" in apple_markdown
        assert "No es asesoramiento financiero" in apple_markdown


class TestProvenanceSeparation:
    def test_quality_counts_match_registry(self, apple_report):
        counts = apple_report.result.registry.level_counts()
        quality = apple_report.quality_summary()
        assert quality["validated"] == counts[ProvenanceLevel.EXTERNAL_VALIDATED.value]
        assert quality["corroborated"] == counts[ProvenanceLevel.EXTERNAL_CORROBORATED.value]
        assert quality["downloaded_only"] == counts[ProvenanceLevel.EXTERNAL_DOWNLOADED.value]
        assert quality["total"] == len(apple_report.result.registry.observations)

    def test_validated_facts_show_document_reference(self, apple_markdown):
        assert "accn=0000320193" in apple_markdown
        assert "form=10-K" in apple_markdown
        assert "filed=" in apple_markdown

    def test_unvalidated_observations_are_separated(self, apple_report, apple_markdown):
        unvalidated = apple_report.observations_by_level(
            ProvenanceLevel.EXTERNAL_DOWNLOADED
        )
        if not unvalidated:
            pytest.skip("el recorte del fixture no conserva periodos no promovidos")
        assert "no se usan para calcular conclusiones" in apple_markdown.lower()

    def test_download_is_not_presented_as_verification(self, apple_markdown):
        assert "no demuestra que la cifra sea cierta" in apple_markdown
        assert "no una segunda" in apple_markdown

    def test_simulated_data_is_flagged(self, simulated_report):
        text = simulated_report.markdown()
        assert "contiene datos simulados" in text
        assert "no debe interpretarse como información real" in text
        assert simulated_report.quality_summary()["simulated"] == 13
        assert simulated_report.quality_summary()["validated"] == 0


class TestMissingData:
    def test_ttm_absence_is_explained(self, apple_report, apple_markdown):
        assert apple_report.metrics.revenue_ttm is None
        assert "Ingresos TTM: **no disponibles**" in apple_markdown
        assert "acumulados YTD no sirven" in apple_markdown

    def test_missing_metrics_are_listed_not_zeroed(self, apple_report, simulated_report):
        # Apple presenta inventario, así que su informe no tiene ausencias principales;
        # el registro simulado sí, y esas ausencias deben aparecer nombradas.
        assert apple_report.missing_headline_metrics() == []
        missing = dict(simulated_report.missing_headline_metrics())
        assert "inventory" in missing
        assert simulated_report.metrics.inventory is None
        assert simulated_report.metrics.current_ratio is None

    def test_report_never_uses_zero_for_missing(self, simulated_report):
        assert "sin dato. No se asume cero." in simulated_report.markdown()

    def test_registry_without_revenue_cannot_be_dated(self, simulated_report):
        registry = ProvenanceRegistry()
        source = DataSource(
            id="vacio",
            name="Vacío",
            entity="Sin datos S.A.",
            origin=DataOrigin.SIMULATED,
            verification_state=VerificationState.UNVERIFIED,
        )
        registry.register_source(source)
        result = SecEdgarResult(
            cik=2, entity_name="Sin datos S.A.", registry=registry, facts={}, fetch_records=[]
        )
        with pytest.raises(ValueError, match="No hay observaciones de ingresos"):
            build_real_report(result, generated_at=GENERATED_AT)


class TestValuation:
    def test_three_scenarios_are_built(self, apple_report):
        names = [s.scenario.name for s in apple_report.scenarios]
        assert names == ["bajista", "base", "alcista"]

    def test_discount_rate_exceeds_terminal_growth(self, apple_report):
        for result in apple_report.scenarios:
            assert result.dcf.assumptions.discount_rate > result.dcf.assumptions.terminal_growth

    def test_no_upside_without_verified_price(self, apple_report, apple_markdown):
        for result in apple_report.scenarios:
            assert result.upside is None
        assert "Precio de mercado verificado: **no disponible**" in apple_markdown
        assert "margen de subida o bajada" in apple_markdown

    def test_with_verified_price_the_section_states_it(self):
        """Con precio comprobado el informe no puede seguir diciendo que no hay."""

        report = build_real_report(
            _apple_result(), generated_at=GENERATED_AT, share_price=347.10
        )
        text = report.markdown()
        assert "Precio de mercado verificado: **347.10** USD" in text
        assert "Precio de mercado verificado: **no disponible**" not in text
        assert "dos fuentes" in text
        for result in report.scenarios:
            assert result.upside is not None
            expected = result.per_share_value / 347.10 - 1.0
            assert result.upside == pytest.approx(expected)

    def test_equity_value_subtracts_net_debt(self, apple_report):
        for result in apple_report.scenarios:
            expected = result.dcf.enterprise_value - apple_report.metrics.net_debt.value
            assert result.dcf.equity_value == pytest.approx(expected)

    def test_valuation_chain_matches_independent_calculation(self, simulated_report):
        """Recalcula el escenario base con aritmética independiente.

        FCF base = 250 (flujo operativo) - 50 (inversiones) = 200, estimado porque la
        empresa simulada no lo reporta. Con crecimiento 4 %, descuento 8,5 %, valor
        terminal 2,5 % constante y 5 años, el valor por acción se calcula aquí paso a
        paso, sin usar el motor, y debe coincidir.
        """

        fcf = 200.0
        growth, rate, terminal = 0.04, 0.085, 0.025
        years = 5
        pv_explicit = 0.0
        projected = fcf
        for year in range(1, years + 1):
            projected *= 1.0 + growth
            pv_explicit += projected / (1.0 + rate) ** year
        terminal_value = projected * (1.0 + terminal) / (rate - terminal)
        terminal_pv = terminal_value / (1.0 + rate) ** years
        enterprise_value = pv_explicit + terminal_pv
        net_debt = 500.0 - 150.0  # deuda observada - caja observada
        equity_value = enterprise_value - net_debt
        per_share = equity_value / 100.0

        base = simulated_report.scenarios[1]
        assert simulated_report.metrics.free_cash_flow.value == pytest.approx(fcf)
        assert simulated_report.metrics.free_cash_flow_estimated is True
        assert base.dcf.enterprise_value == pytest.approx(enterprise_value)
        assert base.dcf.equity_value == pytest.approx(equity_value)
        assert base.per_share_value == pytest.approx(per_share)

    def test_scenario_order_is_bear_base_bull(self, simulated_report):
        bear, base, bull = simulated_report.scenarios
        assert bear.per_share_value < base.per_share_value < bull.per_share_value


class TestInvalidationRules:
    def test_rules_are_objective_and_numbered(self, apple_report):
        rules = apple_report.invalidation_conditions
        assert len(rules) >= 5
        assert any("Márgen bruto por debajo" in r for r in rules)
        assert any("Deuda neta / EBITDA por encima" in r for r in rules)

    def test_current_values_are_reported_against_rules(self, apple_markdown):
        assert "Condiciones objetivas que invalidarían la tesis" in apple_markdown
        assert "Esto no valida la tesis" in apple_markdown or "no queda respaldada" in apple_markdown

    def test_violated_threshold_is_detected(self):
        report = build_real_report(_simulated_result(), generated_at=GENERATED_AT)
        # Fuerza un margen bruto por debajo del umbral y recompone las reglas.
        report.metrics.gross_margin = 0.05
        report.invalidated.clear()
        report.build_invalidation_rules()
        assert any("margen bruto" in item for item in report.invalidated)


class TestRealFiguresInReport:
    def test_latest_annual_figures_appear(self, apple_report, apple_markdown):
        # Ejercicio 2025 de Apple (cierre 2025-09-27): ingresos 416 161 millones USD,
        # resultado neto 112 010 millones USD y flujo operativo 111 482 millones USD
        # según el 10-K presentado. El informe usa el cierre anual más reciente.
        assert apple_report.metrics.revenue.value == pytest.approx(416_161_000_000)
        assert apple_report.metrics.net_income.value == pytest.approx(112_010_000_000)
        assert "416.2 mil millones USD" in apple_markdown

    def test_period_of_latest_annual_close(self, apple_report):
        assert apple_report.latest_end == date(2025, 9, 27)

    def test_calendar_inferred_from_annual_closes(self, apple_report):
        assert apple_report.calendar == FiscalCalendar(close_month=9)


class TestSensitivitySection:
    """La sensibilidad del escenario base forma parte del informe, con supuestos visibles."""

    @staticmethod
    def _filas(section: str):
        filas = []
        for linea in section.splitlines():
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            if len(celdas) >= 2 and "%" in celdas[0]:
                filas.append(celdas)
        return filas

    def test_section_present_in_report(self, apple_markdown):
        assert "### Sensibilidad del escenario base" in apple_markdown
        assert "| Tasa de descuento |" in apple_markdown

    def test_section_is_not_a_price_target(self, apple_markdown):
        text = apple_markdown
        inicio = text.index("### Sensibilidad del escenario base")
        bloque = text[inicio : text.index("## 8.", inicio)]
        assert "no es" in bloque and "previsión" in bloque
        assert "no es un rango de precio objetivo" in bloque

    def test_table_has_three_rates_and_numeric_cells(self, apple_report):
        filas = self._filas(apple_report._sensitivity_section())
        assert len(filas) == 3
        for celdas in filas:
            assert len(celdas) == 4  # tasa + tres crecimientos terminales
            for valor in celdas[1:]:
                float(valor.replace(",", ""))

    def test_value_falls_as_discount_rate_rises(self, apple_report):
        filas = self._filas(apple_report._sensitivity_section())
        primera_columna = [float(f[1].replace(",", "")) for f in filas]
        assert primera_columna[0] > primera_columna[1] > primera_columna[2]

    def test_value_rises_with_terminal_growth(self, apple_report):
        filas = self._filas(apple_report._sensitivity_section())
        base = next(f for f in filas if "(base)" in f[0])
        valores = [float(v.replace(",", "")) for v in base[1:]]
        assert valores[0] < valores[1] < valores[2]

    def test_sensitivity_absent_without_scenarios(self, apple_report):
        report = build_real_report(_apple_result(), generated_at=GENERATED_AT)
        report.scenarios = []
        assert report._sensitivity_section() == ""
