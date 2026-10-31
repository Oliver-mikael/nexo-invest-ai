"""Pruebas locales del analizador Inline XBRL.

Todas las pruebas son locales: usan HTML de muestra sintético o el fixture real del
10-K de Apple FY2025 que ya está en el repositorio. Ninguna depende de Internet.

Lo que se comprueba aquí es la corrección de la extracción (contexto, unidad,
formato, escala, signo, nil y ambigüedad). NO prueba la descarga del documento:
la descarga automática sigue fuera de alcance.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from nexo_invest.data.inline_xbrl import (
    REVENUE_CONCEPT,
    USD_MEASURE,
    AmbiguousFactError,
    FactNotFoundError,
    InlineXbrlDocument,
    InvalidFactError,
    ResolvedFact,
    UnknownContextError,
    UnsupportedFormatError,
    document_sha256,
    extract_annual_revenue,
    parse_document,
    resolve_number,
    select_fact,
)

FIXTURES = Path(__file__).parent / "fixtures"
CORE_HTML = FIXTURES / "inline_xbrl" / "sample_core.htm"
AMBIGUOUS_HTML = FIXTURES / "inline_xbrl" / "sample_ambiguous.htm"
APPLE_HTML = FIXTURES / "sec_docs" / "aapl-20250927.htm"
APPLE_COMPANYFACTS = FIXTURES / "sec_companyfacts_aapl_subset.json"

# SHA-256 del HTML descargado el 2026-10-28 y registrado en la sesión anterior.
APPLE_SHA256 = "b9820c677562512182ea9d48a02219d46859e25458087118baa8fb6defd225d3"
FY2025_START = date(2024, 9, 29)
FY2025_END = date(2025, 9, 27)
FY2024_START = date(2023, 10, 1)
FY2024_END = date(2024, 9, 28)


@pytest.fixture(scope="module")
def core_doc() -> InlineXbrlDocument:
    return parse_document(CORE_HTML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ambiguous_doc() -> InlineXbrlDocument:
    return parse_document(AMBIGUOUS_HTML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def apple_doc() -> InlineXbrlDocument:
    return parse_document(APPLE_HTML.read_text(encoding="utf-8"))


def _select(doc: InlineXbrlDocument, concept: str, **kwargs) -> ResolvedFact:
    kwargs.setdefault("period_start", FY2025_START)
    kwargs.setdefault("period_end", FY2025_END)
    return select_fact(doc, concept=concept, **kwargs)


class TestDocumentSha256:
    def test_sha256_of_known_bytes(self) -> None:
        # Vector de referencia (SHA-256 de "abc").
        assert (
            document_sha256(b"abc")
            == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_hash_changes_with_content(self) -> None:
        assert document_sha256(b"abc") != document_sha256(b"abd")

    def test_apple_fixture_matches_registered_hash(self) -> None:
        assert document_sha256(APPLE_HTML.read_bytes()) == APPLE_SHA256


class TestContextsAndUnits:
    def test_consolidated_context_has_no_dimensions(self, core_doc) -> None:
        ctx = core_doc.contexts["c-annual"]
        assert ctx.is_consolidated
        assert ctx.dimensions == ()
        assert ctx.start == FY2025_START and ctx.end == FY2025_END
        assert not ctx.is_instant

    def test_dimensioned_context_records_the_dimension(self, core_doc) -> None:
        ctx = core_doc.contexts["c-annual-dim"]
        assert not ctx.is_consolidated
        assert ctx.dimensions == ("srt:ProductOrServiceAxis=us-gaap:ProductMember",)

    def test_instant_context_is_not_a_duration(self, core_doc) -> None:
        ctx = core_doc.contexts["c-instant"]
        assert ctx.is_instant and ctx.start is None
        assert ctx.end == FY2025_END
        # Un instante no puede igualarse a un periodo de duración.
        assert not ctx.matches_period(date(2025, 9, 27), FY2025_END)

    def test_units_are_resolved_to_their_measure(self, core_doc) -> None:
        assert core_doc.units["usd"] == "iso4217:USD"
        assert core_doc.units["shares"] == "xbrli:shares"

    def test_composite_unit_is_marked_unsupported(self, core_doc) -> None:
        # Unidad con xbrli:divide: se marca como no soportada, no se adivina.
        assert core_doc.units["mixed"] is None

    def test_unknown_context_is_rejected_not_guessed(self, core_doc) -> None:
        with pytest.raises(UnknownContextError):
            _select(core_doc, "test:UnknownCtx")

    def test_document_without_xbrl_content_is_rejected(self) -> None:
        with pytest.raises(InvalidFactError, match="Inline XBRL"):
            parse_document("<html><body><p>sin marcado iXBRL</p></body></html>")


class TestScale:
    def test_scale_zero(self, core_doc) -> None:
        assert _select(core_doc, "test:ScaleZero").value == Decimal("1234")

    def test_scale_three(self, core_doc) -> None:
        assert _select(core_doc, "test:ScaleThree").value == Decimal("1234000")

    def test_scale_six(self, core_doc) -> None:
        fact = _select(core_doc, REVENUE_CONCEPT)
        assert fact.value == Decimal("416161000000")

    def test_negative_scale(self, core_doc) -> None:
        # 1,234 con scale=-3 -> 1.234: decimales exactos, sin coma flotante.
        assert _select(core_doc, "test:ScaleNegative").value == Decimal("1.234")

    def test_missing_scale_is_factor_one(self, core_doc) -> None:
        assert _select(core_doc, "test:NoScale").value == Decimal("500")

    def test_unreadable_scale_is_rejected_not_treated_as_one(self, core_doc) -> None:
        with pytest.raises(InvalidFactError, match="scale"):
            _select(core_doc, "test:BadScale")

    def test_values_are_decimal_not_float(self, core_doc) -> None:
        assert isinstance(_select(core_doc, "test:ScaleNegative").value, Decimal)


class TestSign:
    def test_sign_negative_attribute(self, core_doc) -> None:
        assert _select(core_doc, "test:SignNegative").value == Decimal("-9876")

    def test_sign_positive_attribute(self, core_doc) -> None:
        assert _select(core_doc, "test:SignPositive").value == Decimal("9876")

    def test_leading_minus_in_text(self, core_doc) -> None:
        assert _select(core_doc, "test:LeadingMinus").value == Decimal("-9876")

    def test_unknown_sign_value_is_rejected(self, core_doc) -> None:
        with pytest.raises(InvalidFactError, match="sign"):
            _select(core_doc, "test:BadSign")


class TestNumericFormats:
    def test_dot_decimal_with_thousands_and_scale(self) -> None:
        assert resolve_number(
            "416,161", scale=6, sign=None, format="ixt:num-dot-decimal"
        ) == Decimal("416161000000")

    def test_comma_decimal(self) -> None:
        assert resolve_number(
            "1.234,56", scale=0, sign=None, format="ixt:num-comma-decimal"
        ) == Decimal("1234.56")

    def test_numdash_trailing_minus(self) -> None:
        assert resolve_number(
            "9,876-", scale=0, sign=None, format="ixt:numdash"
        ) == Decimal("-9876")

    def test_numdash_with_explicit_sign_does_not_double_negate(self) -> None:
        assert resolve_number(
            "9,876-", scale=0, sign="-", format="ixt:numdash"
        ) == Decimal("-9876")

    def test_integer_without_format(self) -> None:
        assert resolve_number("500", scale=None, sign=None, format=None) == Decimal("500")

    def test_decimal_without_format_is_rejected(self) -> None:
        # "1.234" es ambiguo (1.234 o 1.234 en otra notación): se rechaza.
        with pytest.raises(InvalidFactError, match="enteros"):
            resolve_number("1.234", scale=None, sign=None, format=None)

    def test_unknown_format_is_rejected_and_typed(self) -> None:
        with pytest.raises(UnsupportedFormatError) as excinfo:
            resolve_number(
                "1,234", scale=0, sign=None, format="ixt:fixed-zero"
            )
        assert isinstance(excinfo.value, InvalidFactError)

    def test_trailing_minus_not_allowed_for_dot_decimal(self) -> None:
        with pytest.raises(InvalidFactError):
            resolve_number("9,876-", scale=0, sign=None, format="ixt:num-dot-decimal")

    def test_nbsp_is_removed(self) -> None:
        assert resolve_number(
            "\u00a0416,161\u00a0", scale=0, sign=None, format="ixt:num-dot-decimal"
        ) == Decimal("416161")

    def test_narrow_nbsp_is_removed(self) -> None:
        assert resolve_number(
            "\u202f512\u202f", scale=0, sign=None, format="ixt:num-dot-decimal"
        ) == Decimal("512")

    def test_internal_ascii_space_is_not_reinterpreted(self) -> None:
        with pytest.raises(InvalidFactError):
            resolve_number("416, 161", scale=0, sign=None, format="ixt:num-dot-decimal")

    def test_empty_text_is_rejected(self) -> None:
        with pytest.raises(InvalidFactError, match="sin valor"):
            resolve_number("   ", scale=0, sign=None, format=None)
        with pytest.raises(InvalidFactError, match="sin valor"):
            resolve_number("\u00a0\u00a0", scale=0, sign=None, format=None)

    def test_present_but_empty_fact_is_rejected(self, core_doc) -> None:
        with pytest.raises(InvalidFactError, match="sin valor"):
            _select(core_doc, "test:EmptyText")


class TestNilAndMissingData:
    def test_nil_fact_does_not_produce_a_value(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError, match="nil"):
            _select(core_doc, "test:Nil")

    def test_non_numeric_text_is_invalid_not_skipped(self, core_doc) -> None:
        with pytest.raises(InvalidFactError):
            _select(core_doc, "test:BadText")

    def test_missing_concept(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError, match="ausente"):
            _select(core_doc, "test:NoExiste")

    def test_missing_period_is_reported_with_available_periods(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError) as excinfo:
            _select(core_doc, REVENUE_CONCEPT, period_start=date(2026, 1, 1),
                    period_end=date(2026, 12, 31))
        assert "2024-09-29..2025-09-27" in str(excinfo.value)

    def test_instant_fact_is_not_selected_for_a_duration(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError):
            _select(core_doc, "test:InstantFact")


class TestSelectionRules:
    def test_consolidated_fact_is_selected_over_segmented_ones(self, core_doc) -> None:
        fact = _select(core_doc, REVENUE_CONCEPT)
        assert fact.fact_id == "f-1"
        assert fact.context_id == "c-annual"
        assert fact.dimensions == ()
        assert fact.unit_measure == USD_MEASURE
        assert fact.value == Decimal("416161000000")

    def test_duplicate_facts_with_equal_value_are_accepted(self, core_doc) -> None:
        # f-1 ("416,161" con formato) y f-2 ("416161" sin formato) valen lo mismo.
        candidates = core_doc.facts_for(REVENUE_CONCEPT)
        assert len(candidates) == 4
        fact = _select(core_doc, REVENUE_CONCEPT)
        assert fact.value == Decimal("416161000000")

    def test_wrong_period_is_not_matched(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError):
            _select(core_doc, REVENUE_CONCEPT, period_start=FY2024_START,
                    period_end=FY2024_END)

    def test_wrong_unit_is_not_matched(self, core_doc) -> None:
        with pytest.raises(FactNotFoundError, match="unidad"):
            _select(core_doc, REVENUE_CONCEPT, unit_measure="xbrli:shares")

    def test_correct_unit_is_matched(self, core_doc) -> None:
        fact = _select(core_doc, "test:SharesOnly", unit_measure="xbrli:shares")
        assert fact.unit_measure == "xbrli:shares"
        assert fact.value == Decimal("1234")

    def test_composite_unit_is_rejected_explicitly(self, core_doc) -> None:
        with pytest.raises(InvalidFactError, match="compuesta"):
            _select(core_doc, "test:CompositeUnit", unit_measure=USD_MEASURE)

    def test_dimensioned_facts_make_the_result_ambiguous_not_first_wins(self, core_doc) -> None:
        # Sin exigir contexto consolidado aparecen valores distintos del mismo periodo.
        with pytest.raises(AmbiguousFactError):
            _select(core_doc, REVENUE_CONCEPT, require_no_dimensions=False)

    def test_missing_context_reference_is_invalid(self, core_doc) -> None:
        with pytest.raises(UnknownContextError):
            _select(core_doc, "test:UnknownCtx")


class TestAmbiguity:
    def test_different_values_in_two_contexts_are_ambiguous(self, ambiguous_doc) -> None:
        with pytest.raises(AmbiguousFactError) as excinfo:
            _select(ambiguous_doc, "test:AmbiguousContexts")
        message = str(excinfo.value)
        assert "416161000000" in message and "415000000000" in message
        assert "a-1" in message and "a-2" in message

    def test_different_values_in_one_context_are_ambiguous(self, ambiguous_doc) -> None:
        with pytest.raises(AmbiguousFactError):
            _select(ambiguous_doc, "test:AmbiguousSameContext")

    def test_duplicated_equal_values_are_not_ambiguous(self, ambiguous_doc) -> None:
        fact = _select(ambiguous_doc, "test:DuplicateEqual")
        assert fact.value == Decimal("416161000000")
        assert fact.context_id in ("c-a", "c-b")


class TestAppleFY2025Fixture:
    """Validación sobre el 10-K real de Apple FY2025 ya presente en el repositorio."""

    def test_document_structure(self, apple_doc) -> None:
        # Fija el fixture: 182 contextos y 969 hechos ix:nonFraction.
        assert len(apple_doc.contexts) == 182
        assert len(apple_doc.facts) == 969

    def test_consolidated_revenue_fy2025(self, apple_doc) -> None:
        fact = extract_annual_revenue(apple_doc, period_start=FY2025_START,
                                      period_end=FY2025_END)
        assert fact.value == Decimal("416161000000")
        assert fact.unit_measure == USD_MEASURE
        assert fact.dimensions == ()
        assert fact.context_id == "c-1"
        assert fact.scale == 6
        assert fact.format == "ixt:num-dot-decimal"
        assert fact.raw_text.strip() == "416,161"
        assert fact.fact_id == "f-78"

    @pytest.mark.parametrize(
        "start,end,expected",
        [
            (FY2024_START, FY2024_END, Decimal("391035000000")),
            (date(2022, 9, 25), date(2023, 9, 30), Decimal("383285000000")),
        ],
    )
    def test_previous_fiscal_years(self, apple_doc, start, end, expected) -> None:
        fact = extract_annual_revenue(apple_doc, period_start=start, period_end=end)
        assert fact.value == expected
        assert fact.dimensions == ()

    def test_segmented_facts_of_the_same_period_are_excluded(self, apple_doc) -> None:
        dimensioned = [
            f for f in apple_doc.facts_for(REVENUE_CONCEPT)
            if apple_doc.contexts[f.context_id].matches_period(FY2025_START, FY2025_END)
            and apple_doc.contexts[f.context_id].dimensions
        ]
        assert len(dimensioned) == 15
        # Si se permitieran hechos dimensionados, el resultado sería ambiguo: el
        # analizador nunca elegiría un segmento por ser el primero.
        with pytest.raises(AmbiguousFactError):
            select_fact(
                apple_doc,
                concept=REVENUE_CONCEPT,
                period_start=FY2025_START,
                period_end=FY2025_END,
                unit_measure=USD_MEASURE,
                require_no_dimensions=False,
            )

    def test_value_coincides_with_companyfacts_json(self, apple_doc) -> None:
        """Coincide con la API CompanyFacts de la SEC para el mismo periodo.

        Ambas cifras proceden de la MISMA presentación (accession
        0000320193-25-000079): el HTML iXBRL y la API JSON son dos formatos del
        mismo documento. La coincidencia confirma que la extracción del HTML es
        correcta; NO demuestra independencia entre fuentes.
        """
        fact = extract_annual_revenue(apple_doc, period_start=FY2025_START,
                                      period_end=FY2025_END)
        payload = json.loads(APPLE_COMPANYFACTS.read_text(encoding="utf-8"))
        # La API CompanyFacts agrupa por taxonomía y nombre de concepto sin prefijo.
        concept_key = REVENUE_CONCEPT.split(":", 1)[1]
        entries = payload["facts"]["us-gaap"][concept_key]["units"]["USD"]
        matches: List[dict] = [
            e for e in entries
            if e.get("start") == "2024-09-29"
            and e.get("end") == "2025-09-27"
            and e.get("form") == "10-K"
        ]
        assert len(matches) == 1
        record = matches[0]
        assert record["accn"] == "0000320193-25-000079"
        assert Decimal(record["val"]) == fact.value
