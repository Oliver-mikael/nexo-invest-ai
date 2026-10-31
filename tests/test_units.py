from __future__ import annotations

import pytest
from datetime import date

from nexo_invest.core.units import Money, Period, Frequency, Scale


class TestMoney:
    def test_money_basic(self):
        m = Money(120.0, "USD", Scale.MILLIONS, "ingresos")
        assert m.value == 120.0
        assert m.currency == "USD"
        assert m.scale is Scale.MILLIONS
        assert m.label == "ingresos"

    def test_money_missing(self):
        m = Money(float("nan"), "USD", "millions")
        assert m.is_missing is True

    def test_money_not_missing_value_zero(self):
        m = Money(0.0, "USD", "millions")
        assert m.is_missing is False

    def test_money_invalid_scale(self):
        with pytest.raises(ValueError, match="Escala no soportada"):
            Money(1.0, scale="billionszzzz")

    def test_money_repr(self):
        m = Money(100.0, "EUR", Scale.THOUSANDS, "prueba")
        r = repr(m)
        assert "Money" in r
        assert "EUR" in r

    def test_money_equality(self):
        a = Money(100.0, "USD", Scale.MILLIONS)
        b = Money(100.0, "USD", Scale.MILLIONS)
        assert a == b

    def test_money_inequality_currency(self):
        a = Money(100.0, "USD", Scale.MILLIONS)
        b = Money(100.0, "EUR", Scale.MILLIONS)
        assert a != b

    def test_money_inequality_scale(self):
        a = Money(100.0, "USD", Scale.MILLIONS)
        b = Money(1000.0, "USD", Scale.THOUSANDS)
        assert a != b


class TestPeriod:
    def test_period_valid(self):
        p = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
        assert p.start < p.end

    def test_period_invalid_start_after_end(self):
        with pytest.raises(ValueError, match="Periodo invalido"):
            Period(start=date(2024, 12, 31), end=date(2024, 1, 1), frequency=Frequency.ANNUAL)

    def test_frequency_flags(self):
        assert Frequency.ANNUAL.is_annual() is True
        assert Frequency.ANNUAL.is_quarterly() is False
        assert Frequency.QUARTERLY.is_quarterly() is True
        assert Frequency.TTM.is_ttm() is True

    def test_scale_enum(self):
        assert Scale.MILLIONS.value == "millions"
        assert Scale.THOUSANDS.value == "thousands"
        assert Scale.REPORTED.value == "reported"

    def test_scale_from_str(self):
        assert Scale.from_str("millions") is Scale.MILLIONS
        assert Scale.from_str("thousands") is Scale.THOUSANDS
        assert Scale.from_str("billions") is Scale.BILLIONS
        assert Scale.from_str("units") is Scale.UNITS
        assert Scale.from_str("reported") is Scale.REPORTED
        with pytest.raises(ValueError, match="Escala no soportada"):
            Scale.from_str("billionszzzz")

    def test_money_to_scale_same(self):
        m = Money(120.0, "USD", Scale.MILLIONS, "ingresos")
        assert m.to_scale(Scale.MILLIONS).value == pytest.approx(120.0)
        assert m.to_scale(Scale.MILLIONS).scale is Scale.MILLIONS

    def test_money_to_scale_conversion(self):
        m = Money(1_000_000.0, "USD", Scale.UNITS, "ingresos")
        converted = m.to_scale(Scale.MILLIONS)
        assert converted.value == pytest.approx(1.0)
        assert converted.scale is Scale.MILLIONS

    def test_money_scale_millions_factor(self):
        assert Scale.MILLIONS.to_millions_factor() == pytest.approx(1.0)
        assert Scale.THOUSANDS.to_millions_factor() == pytest.approx(1e-3)
        assert Scale.BILLIONS.to_millions_factor() == pytest.approx(1e3)
        assert Scale.UNITS.to_millions_factor() == pytest.approx(1e-6)

    def test_money_to_scale_preserves_missing(self):
        m = Money(float("nan"), "USD", Scale.MILLIONS)
        assert m.to_scale(Scale.THOUSANDS).is_missing is True
