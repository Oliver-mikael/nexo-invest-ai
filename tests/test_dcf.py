from __future__ import annotations

import pytest

from nexo_invest.core.dcf import (
    DCFAssumptions,
    DCFRun,
    ProjectedYear,
    discount_factor,
    run_dcf,
    sensitivity_table,
)
from nexo_invest.core.units import Money


class TestDiscountFactor:
    def test_df_year1(self):
        assert discount_factor(0.10, 1) == pytest.approx(1.0 / 1.10)

    def test_df_year3(self):
        assert discount_factor(0.10, 3) == pytest.approx(1.0 / 1.10 ** 3)


def _base_assumptions() -> DCFAssumptions:
    return DCFAssumptions(
        currency="USD",
        forecast_years=5,
        discount_rate=0.09,
        terminal_growth=0.025,
        shares_outstanding=50.0,
        share_price=4.0,
        net_debt=Money(60.0, "USD", "millions"),
    )


class TestRunDCF:
    def test_run_produces_positive_values(self):
        base = Money(23.0, "USD", "millions")
        run = run_dcf(base, [0.05, 0.04, 0.03, 0.03, 0.02], _base_assumptions())
        assert len(run.projected_years) == 5
        assert run.terminal_value is not None
        assert run.terminal_value > 0
        assert run.enterprise_value is not None
        assert run.equity_value is not None
        assert run.per_share_value is not None
        assert run.value_per_share() == run.per_share_value

    def test_fcf_grows_by_rate(self):
        base = Money(100.0, "USD", "millions")
        run = run_dcf(base, [0.10, 0.10, 0.10], DCFAssumptions(
            currency="USD", forecast_years=3, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
        ))
        assert run.projected_years[0].free_cash_flow == pytest.approx(110.0)
        assert run.projected_years[1].free_cash_flow == pytest.approx(121.0)
        assert run.projected_years[2].free_cash_flow == pytest.approx(133.1)

    def test_terminal_value_gordon(self):
        base = Money(100.0, "USD", "millions")
        run = run_dcf(base, [0.0], DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
        ))
        # último FCF = 100, TV = 100*1.02/(0.10-0.02) = 1275
        assert run.terminal_value == pytest.approx(1275.0, rel=1e-6)

    def test_missing_base_fcf_raises(self):
        base = Money(float("nan"), "USD", "millions")
        with pytest.raises(ValueError, match="FCF base necesaria"):
            run_dcf(base, [0.05], _base_assumptions())

    def test_invalid_discount_rate_raises(self):
        with pytest.raises(ValueError, match="discount_rate debe ser positivo"):
            DCFAssumptions(currency="USD", forecast_years=3, discount_rate=0.0, terminal_growth=0.02,
                           shares_outstanding=10.0)

    def test_terminal_growth_invalid_raises(self):
        with pytest.raises(ValueError, match="terminal_growth debe estar entre"):
            DCFAssumptions(currency="USD", forecast_years=3, discount_rate=0.08, terminal_growth=0.09,
                           shares_outstanding=10.0)

    def test_net_debt_subtracted(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.20,
            terminal_growth=0.0, shares_outstanding=10.0,
            net_debt=Money(50.0, "USD", "millions"),
        )
        run = run_dcf(base, [0.0], a)
        assert run.equity_value == pytest.approx(run.enterprise_value - 50.0)

    def test_without_net_debt(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.20,
            terminal_growth=0.0, shares_outstanding=10.0,
            net_debt=None,
        )
        run = run_dcf(base, [0.0], a)
        assert run.equity_value == pytest.approx(run.enterprise_value)


class TestUpside:
    def test_upside_positive(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
            share_price=10.0,
        )
        run = run_dcf(base, [0.0], a)
        assert run.upside() is not None
        assert run.upside() > 0

    def test_upside_none_without_price(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
            share_price=None,
        )
        run = run_dcf(base, [0.0], a)
        assert run.upside() is None


class TestSensitivityTable:
    def test_table_keys(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=3, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
        )
        table = sensitivity_table(base, [0.03], a, [0.09, 0.10, 0.11], [0.01, 0.02])
        assert (0.09, 0.01) in table
        assert (0.10, 0.02) in table

    def test_sensitivity_shape(self):
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=2, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
        )
        table = sensitivity_table(base, [0.03], a, [0.09, 0.10], [0.01, 0.02])
        assert len(table) == 4

class TestScenarioAndComparables:
    def test_scenario_params_and_valuation(self):
        from nexo_invest.core.dcf import (
            Scenario, Comparable, multiples_from_comparables,
            build_valuation, ValuationResult, DCFAssumptions, Money
        )
        from nexo_invest.core.sources import DataOrigin, VerificationState
        from nexo_invest.core.units import Scale
        base = Money(100.0, "USD", Scale.MILLIONS)
        scenarios = [
            Scenario(name="bajista", label="Bajista",
                     revenue_growth_rates=[-0.05, -0.03, -0.02],
                     discount_rate=0.12, terminal_growth=0.01),
            Scenario(name="base", label="Base",
                     revenue_growth_rates=[0.05, 0.05, 0.05],
                     discount_rate=0.10, terminal_growth=0.02),
            Scenario(name="alcista", label="Alcista",
                     revenue_growth_rates=[0.10, 0.08, 0.06],
                     discount_rate=0.09, terminal_growth=0.03),
        ]
        results = build_valuation(
            company="Empresa demo",
            base_fcf=base,
            forecast_years=3,
            share_price=2.5,
            shares_outstanding=50.0,
            scenarios=scenarios,
        )
        assert len(results) == 3
        by_name = {r.scenario.name: r for r in results}
        assert by_name["base"].per_share_value is not None
        assert by_name["base"].upside is not None
        assert by_name["base"].upside > 0.0
        assert by_name["bajista"].per_share_value is not None
        assert by_name["alcista"].per_share_value is not None
        # orden esperado: bajista < base < alcista por construcción
        assert by_name["bajista"].per_share_value < by_name["base"].per_share_value
        assert by_name["base"].per_share_value < by_name["alcista"].per_share_value
        assert by_name["base"].dcf.assumptions.discount_rate == 0.10
        assert by_name["base"].dcf.assumptions.terminal_growth == 0.02

    def test_comparable_multiples_simulated(self):
        from nexo_invest.core.dcf import Comparable, multiples_from_comparables
        from nexo_invest.core.sources import DataOrigin, VerificationState
        from nexo_invest.core.units import Money, Scale
        comps = [
            Comparable(
                company="CompA",
                data_origin=DataOrigin.SIMULATED,
                verification_state=VerificationState.UNVERIFIED,
                price=Money(2.5, "USD", Scale.MILLIONS),
                revenue=Money(10.0, "USD", Scale.MILLIONS),
                ebitda=Money(4.0, "USD", Scale.MILLIONS),
                net_income=Money(1.0, "USD", Scale.MILLIONS),
                net_debt=Money(1.0, "USD", Scale.MILLIONS),
            ),
            Comparable(
                company="CompB",
                data_origin=DataOrigin.SIMULATED,
                verification_state=VerificationState.UNVERIFIED,
                price=Money(3.0, "USD", Scale.MILLIONS),
                revenue=Money(12.0, "USD", Scale.MILLIONS),
                ebitda=Money(5.0, "USD", Scale.MILLIONS),
                net_income=Money(1.2, "USD", Scale.MILLIONS),
                net_debt=Money(1.5, "USD", Scale.MILLIONS),
            ),
        ]
        m = multiples_from_comparables(comps)
        assert m["revenue_multiple"] == 0.25
        # PE median de 2.5 (CompA) y 2.5 (3.0/1.2=2.5) = 2.5
        assert m["pe_multiple"] == 2.5
        # EBITDA median: CompA 2.5x, CompB 3.0/5.0=0.6x? espera 3.0/5.0=0.6
        # wait enterprise_value is None -> None; but ebitda_multiple requires enterprise_value
        assert m["ebitda_multiple"] is None

    def test_comparable_ebitda_multiple_needs_ev(self):
        from nexo_invest.core.dcf import Comparable, multiples_from_comparables
        from nexo_invest.core.sources import DataOrigin, VerificationState
        from nexo_invest.core.units import Money, Scale
        comps = [
            Comparable(
                company="CompA",
                data_origin=DataOrigin.SIMULATED,
                verification_state=VerificationState.UNVERIFIED,
                enterprise_value=Money(100.0, "USD", Scale.MILLIONS),
                ebitda=Money(20.0, "USD", Scale.MILLIONS),
                price=Money(2.5, "USD", Scale.MILLIONS),
                revenue=Money(10.0, "USD", Scale.MILLIONS),
            ),
        ]
        m = multiples_from_comparables(comps)
        assert m["ebitda_multiple"] == 5.0
        assert m["revenue_multiple"] == 0.25

    def test_scenario_invalid_terminal_growth(self):
        from nexo_invest.core.dcf import Scenario
        with pytest.raises(ValueError, match="discount_rate"):
            Scenario(
                name="bad",
                label="bad",
                revenue_growth_rates=[0.05],
                discount_rate=0.10,
                terminal_growth=0.10,
            )

    def test_scenario_invalid_terminal_growth_negative(self):
        from nexo_invest.core.dcf import Scenario
        with pytest.raises(ValueError, match="terminal_growth debe ser >= -1"):
            Scenario(
                name="bad",
                label="bad",
                revenue_growth_rates=[0.05],
                discount_rate=0.15,
                terminal_growth=-1.5,
            )

    def test_comparable_insufficient_for_pe(self):
        from nexo_invest.core.dcf import Comparable, multiples_from_comparables
        from nexo_invest.core.sources import DataOrigin, VerificationState
        from nexo_invest.core.units import Money, Scale
        comps = [
            Comparable(
                company="CompA",
                data_origin=DataOrigin.SIMULATED,
                verification_state=VerificationState.UNVERIFIED,
                price=Money(2.5, "USD", Scale.MILLIONS),
                revenue=Money(10.0, "USD", Scale.MILLIONS),
                ebitda=None,
                net_income=None,
            ),
        ]
        m = multiples_from_comparables(comps)
        assert m["pe_multiple"] is None
        assert m["revenue_multiple"] == 0.25

    def test_comparison_requires_scale_match(self):
        from nexo_invest.core.dcf import Comparable, multiples_from_comparables
        from nexo_invest.core.sources import DataOrigin, VerificationState
        from nexo_invest.core.units import Money, Scale
        comps = [
            Comparable(
                company="CompA",
                data_origin=DataOrigin.SIMULATED,
                verification_state=VerificationState.UNVERIFIED,
                price=Money(2.5, "USD", Scale.MILLIONS),
                revenue=Money(10.0, "USD", Scale.THOUSANDS),  # escala incompatible
            ),
        ]
        m = multiples_from_comparables(comps)
        assert m["revenue_multiple"] is None
