from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from nexo_invest import __version__
from nexo_invest.core.dcf import DCFRun, DCFAssumptions, run_dcf
from nexo_invest.core.metrics import FinancialMetrics, FinancialState, IncomeStatement, BalanceSheet, CashFlow
from nexo_invest.core.units import Money, Period, Frequency, Scale
from nexo_invest.core.periods import FiscalCalendar


def version(args: argparse.Namespace) -> None:
    print(f"nexo-invest-ai {__version__}")


def metrics_demo(args: argparse.Namespace) -> None:
    state = FinancialState(company="Ejemplo S.A.", currency="USD")
    p1 = Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL)
    p2 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
    state.add_income_statement(
        IncomeStatement(
            period=p1,
            revenue=Money(100.0, "USD", "millions", "ingresos_anuales"),
            gross_profit=Money(50.0, "USD", "millions"),
            operating_income=Money(18.0, "USD", "millions"),
            net_income=Money(12.0, "USD", "millions"),
            ebitda=Money(22.0, "USD", "millions"),
        )
    )
    state.add_income_statement(
        IncomeStatement(
            period=p2,
            revenue=Money(120.0, "USD", "millions"),
            gross_profit=Money(60.0, "USD", "millions"),
            operating_income=Money(21.0, "USD", "millions"),
            net_income=Money(14.0, "USD", "millions"),
            ebitda=Money(25.0, "USD", "millions"),
        )
    )
    state.add_balance_sheet(
        BalanceSheet(
            period=p2,
            total_debt=Money(80.0, "USD", "millions"),
            cash_and_equivalents=Money(20.0, "USD", "millions"),
            invested_capital=Money(400.0, "USD", "millions"),
        )
    )
    state.add_cash_flow(
        CashFlow(
            period=p2,
            operating_cash_flow=Money(28.0, "USD", "millions"),
            capital_expenditures=Money(5.0, "USD", "millions"),
            free_cash_flow=Money(23.0, "USD", "millions"),
        )
    )

    cal = FiscalCalendar(close_month=12)
    metrics = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31), fiscal_calendar=cal)
    print(metrics.company)
    print(f"Revenue: {metrics.revenue.value}, growth: {metrics.revenue_growth}")
    print(f"Fiscal growth: {metrics.revenue_growth_fiscal}")
    print(f"TTM revenue: {metrics.revenue_ttm.value if metrics.revenue_ttm else None}")
    print(f"Gross margin: {metrics.gross_margin}, operating margin: {metrics.operating_margin}")
    print(f"EBITDA margin: {metrics.ebitda_margin}, net margin: {metrics.net_margin}")
    print(f"FCF: {metrics.free_cash_flow.value if metrics.free_cash_flow else None}")
    print(f"Net debt: {metrics.net_debt.value if metrics.net_debt else None}")
    print(f"ROIC: {metrics.return_on_invested_capital}")

    # Demo DCF sobre estos datos
    base_fcf = metrics.free_cash_flow
    if base_fcf:
        a = DCFAssumptions(
            currency="USD",
            forecast_years=5,
            discount_rate=0.09,
            terminal_growth=0.025,
            shares_outstanding=50.0,
            share_price=4.0,
            net_debt=metrics.net_debt,
        )
        run = run_dcf(base_fcf, [0.05, 0.04, 0.03, 0.03, 0.02], a)
        print(f"EV: {run.enterprise_value:,.2f}")
        print(f"Equity: {run.equity_value:,.2f}")
        print(f"Value/share: {run.per_share_value:,.4f}")
        print(f"Upside: {run.upside():.2%}")


def sec_report(args: argparse.Namespace) -> int:
    """Descarga una empresa real de SEC EDGAR y escribe su informe Markdown."""

    from nexo_invest.analysis import build_real_report
    from nexo_invest.data.sec_edgar import SecEdgarClient, SecEdgarError, analyze_company

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    client = SecEdgarClient(cache_dir=cache_dir)
    if client.contact_is_placeholder:
        print(
            "AVISO: NEXO_SEC_CONTACT no está definido. La SEC exige un User-Agent con "
            "contacto real; usa una dirección propia para evitar un bloqueo HTTP 403.",
            file=sys.stderr,
        )
    try:
        result = analyze_company(
            client,
            cik=args.cik,
            ticker=args.ticker,
            max_annual_periods=args.max_annual_periods,
        )
    except (SecEdgarError, ValueError) as exc:
        print(f"ERROR de descarga: {exc}", file=sys.stderr)
        print(
            "No se ha escrito ningún informe: no se genera análisis a partir de una "
            "fuente que no respondió.",
            file=sys.stderr,
        )
        return 1

    report = build_real_report(
        result,
        forecast_years=args.forecast_years,
        share_price=args.share_price,
    )
    markdown = report.markdown()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")

    quality = report.quality_summary()
    print(f"Empresa: {result.entity_name} (CIK {result.cik})")
    print(f"Observaciones: {quality['total']} ({quality['validated']} validadas, "
          f"{quality['corroborated']} corroboradas, {quality['downloaded_only']} sin validar)")
    print(f"Periodo más reciente: {report.latest_end}")
    print(f"Estado de calidad: {quality['label']}")
    print(f"Informe escrito en: {output}")
    return 0


def screen(args: argparse.Namespace) -> int:
    """Aplica la estrategia de valor a varias empresas reales y escribe el informe."""

    from nexo_invest.analysis import build_real_report
    from nexo_invest.data.sec_edgar import SecEdgarClient, SecEdgarError, analyze_company
    from nexo_invest.strategies import (
        TacticalReadiness,
        screen_value_contrarian,
        strategies_markdown,
    )

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    client = SecEdgarClient(cache_dir=cache_dir)
    if client.contact_is_placeholder:
        print(
            "AVISO: NEXO_SEC_CONTACT no está definido; la SEC puede responder HTTP 403.",
            file=sys.stderr,
        )

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    results = []
    failures = []
    for ticker in tickers:
        try:
            result = analyze_company(client, ticker=ticker)
            report = build_real_report(result)
        except (SecEdgarError, ValueError, KeyError) as exc:
            failures.append((ticker, f"{type(exc).__name__}: {exc}"))
            print(f"{ticker}: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        screen_result = screen_value_contrarian(report.metrics)
        results.append(screen_result)
        print(
            f"{ticker}: {screen_result.status} "
            f"({screen_result.passed_count} cumplen, {screen_result.failed_count} incumplen, "
            f"{screen_result.not_evaluable_count} no evaluables)"
        )

    markdown = strategies_markdown(
        results,
        TacticalReadiness(),
        generated_at=date.today().isoformat(),
        notes=[f"{ticker}: no se pudo analizar ({error})" for ticker, error in failures],
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"Informe de estrategias escrito en: {output}")
    if failures:
        print(
            f"Atención: {len(failures)} empresa(s) no se pudieron analizar; el fallo queda "
            "registrado en el informe.",
            file=sys.stderr,
        )
    return 0


def backtest(args: argparse.Namespace) -> int:
    """Descarga precios reales y ejecuta la prueba histórica exploratoria."""

    from nexo_invest.backtest import BacktestConfig, run_backtest
    from nexo_invest.data.prices import (
        PriceSourceError,
        YahooPriceClient,
        series_from_fixture,
    )

    if args.fixture:
        series = series_from_fixture(Path(args.fixture), symbol=args.symbol)
    else:
        cache_dir = Path(args.cache_dir) if args.cache_dir else None
        client = YahooPriceClient(cache_dir=cache_dir)
        try:
            series = client.fetch_series(args.symbol, range_=args.years_range)
        except PriceSourceError as exc:
            print(f"ERROR de descarga de precios: {exc}", file=sys.stderr)
            print(
                "No se ha escrito ningún informe: sin serie de precios no hay prueba "
                "histórica que hacer, y no se rellena el hueco con datos inventados.",
                file=sys.stderr,
            )
            return 1

    config = BacktestConfig(
        label=args.label,
        lookback_sessions=args.lookback,
        rebalance_every_sessions=args.rebalance,
        commission_per_trade=args.commission,
        slippage=args.slippage,
    )
    result = run_backtest(series, config)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.markdown(), encoding="utf-8")

    full = result.strategy_full
    benchmark = result.benchmark_full
    print(f"Activo: {result.symbol} · {full.sessions} sesiones "
          f"({full.first_date} → {full.last_date})")
    print(f"Estrategia: rentabilidad {full.total_return:.2%}, volatilidad anualizada "
          f"{(full.annualized_volatility or 0):.2%}, caída máxima {full.max_drawdown:.2%}, "
          f"{len(result.closed_trades)} operaciones cerradas")
    if benchmark is not None:
        print(f"Buy & hold: rentabilidad {benchmark.total_return:.2%}, "
              f"caída máxima {benchmark.max_drawdown:.2%}")
    print(f"Informe escrito en: {output}")
    return 0


def _latest_full_year_revenue(registry):
    """Observación de ingresos del último ejercicio fiscal completo publicado."""

    from nexo_invest.core.units import Frequency

    candidates = []
    for obs in registry.observations_for_metric("revenue"):
        if obs.value is None or obs.value.is_missing:
            continue
        if obs.period.frequency is not Frequency.ANNUAL:
            continue
        if obs.period.start is None:
            continue
        days = (obs.period.end - obs.period.start).days
        if not 330 <= days <= 400:
            continue
        if obs.period.end > date.today():
            continue
        candidates.append(obs)
    if not candidates:
        return None
    return max(candidates, key=lambda o: o.period.end)


def verify(args: argparse.Namespace) -> int:
    """Contrasta los datos con una segunda fuente y valora con el precio comprobado."""

    from nexo_invest.analysis import build_real_report
    from nexo_invest.backtest import BacktestConfig, audit_backtest, run_backtest
    from nexo_invest.data.nasdaq import (
        NasdaqClient,
        NasdaqError,
        financials_from_fixture,
        historical_from_fixture,
    )
    from nexo_invest.data.prices import (
        PriceSourceError,
        YahooPriceClient,
        series_from_fixture,
    )
    from nexo_invest.data.sec_edgar import SecEdgarError, SecEdgarClient, analyze_company
    from nexo_invest.core.sources import ProvenanceLevel
    from nexo_invest.verification import (
        ContrastStatus,
        contrast_annual_revenue,
        contrast_close_price,
        contrast_failed,
        margin_of_safety,
        verification_markdown,
    )

    ticker = args.ticker.upper().strip()

    # -- 1. fuente primaria: SEC EDGAR ----------------------------------------------
    sec_cache = Path(args.cache_dir) if args.cache_dir else None
    sec_client = SecEdgarClient(cache_dir=sec_cache)
    if sec_client.contact_is_placeholder:
        print(
            "AVISO: NEXO_SEC_CONTACT no está definido; la SEC puede responder HTTP 403.",
            file=sys.stderr,
        )
    try:
        result = analyze_company(sec_client, ticker=ticker)
    except (SecEdgarError, ValueError) as exc:
        print(f"ERROR de descarga en SEC EDGAR: {exc}", file=sys.stderr)
        print("No se ha escrito ninguna verificación sin fuente primaria.", file=sys.stderr)
        return 1

    revenue_obs = _latest_full_year_revenue(result.registry)
    if revenue_obs is None:
        print(
            "ERROR: la fuente primaria no publica un ejercicio fiscal completo de ingresos "
            "para este ticker; no se compara nada.",
            file=sys.stderr,
        )
        return 1

    # -- 2. segunda fuente: Nasdaq ----------------------------------------------------
    revenue_limitations_extra = []
    if args.nasdaq_financials_fixture:
        try:
            financials = financials_from_fixture(
                Path(args.nasdaq_financials_fixture), ticker=ticker
            )
        except (NasdaqError, ValueError, OSError) as exc:
            print(f"ERROR leyendo fixture de Nasdaq: {exc}", file=sys.stderr)
            return 1
        revenue_limitations_extra.append(
            "Segunda fuente cargada de un fixture local (copia congelada de una descarga "
            "real). Antes de usarlo en una decisión hay que volver a consultar la fuente."
        )
    else:
        price_cache = Path(args.cache_dir) if args.cache_dir else None
        try:
            financials = NasdaqClient(cache_dir=price_cache).financials(ticker)
        except (NasdaqError, ValueError) as exc:
            print(f"AVISO: la segunda fuente no respondió: {exc}", file=sys.stderr)
            financials = None

    if financials is not None:
        revenue_contrast = contrast_annual_revenue(
            metric="revenue",
            period_end=revenue_obs.period.end,
            primary_value=float(revenue_obs.value.value),
            primary_url=revenue_obs.source.url or result.source_url(),
            primary_retrieval=revenue_obs.source.retrieval_date or result.fetch_records[0].retrieved_at.date(),
            primary_reference=(revenue_obs.notes or "sin referencia"),
            secondary=financials,
        )
    else:
        revenue_contrast = contrast_failed(
            metric="revenue",
            period_end=revenue_obs.period.end,
            primary_value=float(revenue_obs.value.value),
            reason="La segunda fuente no respondió; no hay contraste posible.",
        )
    revenue_contrast.limitations.extend(revenue_limitations_extra)

    # -- registro de la segunda fuente y promoción de la cifra primaria ----------------
    # La segunda fuente se registra como `DataSource` (URL, consulta, hash, límites),
    # pero NO se crea una observación paralela: conviviría en el mismo periodo con la
    # cifra primaria, en distinta escala, y podría sustituirla en el estado financiero.
    # La evidencia del contraste queda como nota y como subida de nivel de la
    # observación primaria, que es donde se rastrea el dato hasta el informe.
    registered_secondary = None
    if financials is not None and financials.source is not None:
        if financials.source.id not in result.registry.sources:
            result.registry.register_source(financials.source)
        registered_secondary = financials.source.id
    if revenue_contrast.status is ContrastStatus.MATCH:
        evidence = (
            f" | corroboración externa: {revenue_contrast.secondary_source} "
            f"({revenue_contrast.secondary_url}) consulta "
            f"{revenue_contrast.secondary_retrieval} columna igual para el cierre "
            f"{revenue_obs.period.end.isoformat()}, unidad inferida ×"
            f"{revenue_contrast.inferred_unit_factor:g}, diferencia relativa "
            f"{revenue_contrast.relative_difference:.6f}"
        )
        revenue_obs.provenance_level = ProvenanceLevel.EXTERNAL_CORROBORATED
        revenue_obs.notes = (revenue_obs.notes or "") + evidence
        revenue_contrast.reasons.append(
            "Trazabilidad: fuente secundaria registrada en el registro de procedencia "
            f"«{registered_secondary}» y la observación primaria de ingresos del cierre "
            f"{revenue_obs.period.end.isoformat()} pasó a "
            f"{revenue_obs.provenance_level.value} con esa evidencia en sus notas."
        )

    # -- 3. precio comprobado en dos fuentes ------------------------------------------
    if args.price_fixture:
        try:
            series = series_from_fixture(Path(args.price_fixture), symbol=ticker)
        except (ValueError, OSError, KeyError) as exc:
            print(f"ERROR leyendo fixture de precios: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            series = YahooPriceClient(cache_dir=Path(args.cache_dir) if args.cache_dir else None).fetch_series(
                ticker, range_=args.price_range
            )
        except PriceSourceError as exc:
            print(f"AVISO: sin serie de precios: {exc}", file=sys.stderr)
            series = None

    price_evidence = None
    price_note = (
        "No hay precio comprobado: no se calcula margen de seguridad ni margen de subida."
    )
    if series is not None and len(series.dates):
        if args.nasdaq_history_fixture:
            try:
                history = historical_from_fixture(Path(args.nasdaq_history_fixture), ticker=ticker)
            except (NasdaqError, ValueError, OSError) as exc:
                print(f"ERROR leyendo histórico de Nasdaq: {exc}", file=sys.stderr)
                return 1
        else:
            try:
                history = NasdaqClient(
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None
                ).historical(ticker, start=series.dates[0], end=series.dates[-1])
            except (NasdaqError, ValueError) as exc:
                print(f"AVISO: sin histórico de la segunda fuente: {exc}", file=sys.stderr)
                history = None

        if history is not None and history.dates:
            if args.price_date:
                try:
                    price_day = date.fromisoformat(args.price_date)
                except ValueError:
                    print(f"ERROR: fecha de precio inválida: {args.price_date}", file=sys.stderr)
                    return 1
            else:
                common = [d for d in history.dates if d in set(series.dates)]
                price_day = max(common) if common else None
            if price_day is None:
                print(
                    "AVISO: las dos fuentes no comparten ninguna fecha de negociación; "
                    "no se declara ningún precio.",
                    file=sys.stderr,
                )
            else:
                price_evidence = contrast_close_price(
                    symbol=ticker,
                    when=price_day,
                    primary=series,
                    primary_source_name="Yahoo Finance · chart (cierre sin ajustar)",
                    primary_url=series.source.url if series.source else None,
                    primary_retrieval=series.fetch.retrieved_at.date() if series.fetch else None,
                    secondary=history,
                )
                if price_evidence.usable_for_margin_of_safety:
                    price_note = (
                        f"Cierre sin ajustar de {price_day.isoformat()} coincidente en "
                        "Yahoo Finance y Nasdaq; nivel EXTERNAL_CORROBORATED. Ninguna de "
                        "las dos fuentes es el mercado oficial."
                    )
                else:
                    price_note = (
                        f"Cierre del {price_day.isoformat()} no coincidente entre fuentes: "
                        "no se usa para calcular margen de seguridad."
                    )

    usable_price = (
        price_evidence.close if price_evidence is not None and price_evidence.usable_for_margin_of_safety else None
    )

    # -- 4. valoración con el precio comprobado ----------------------------------------
    report = build_real_report(
        result,
        forecast_years=args.forecast_years,
        share_price=usable_price,
    )

    # -- 5. revisión de la prueba histórica ----------------------------------------------
    extra_notes: list[str] = []
    if args.backtest_fixture:
        try:
            bt_series = series_from_fixture(Path(args.backtest_fixture), symbol=ticker)
            bt_result = run_backtest(bt_series, BacktestConfig())
        except (ValueError, OSError, KeyError) as exc:
            print(f"AVISO: no se pudo revisar la prueba histórica: {exc}", file=sys.stderr)
        else:
            audit = audit_backtest(bt_result, bt_series)
            full = bt_result.strategy_full
            bench = bt_result.benchmark_full
            extra_notes.append(
                f"Prueba histórica ({bt_series.dates[0]} → {bt_series.dates[-1]}, "
                f"{full.sessions} sesiones): estrategia {full.total_return:.2%}, "
                f"buy & hold {bench.total_return:.2%}, caída máxima "
                f"{full.max_drawdown:.2%}, {len(bt_result.trades)} entradas y "
                f"{len(bt_result.closed_trades)} operaciones cerradas, comisión "
                f"{bt_result.config.commission_per_trade * 10_000:.0f} pb y deslizamiento "
                f"{bt_result.config.slippage * 10_000:.0f} pb por operación."
            )
            extra_notes.append(
                "La regla **no supera** a comprar y mantener en este periodo: la "
                "diferencia no se oculta ni se reencuadra."
            )
            for line in audit.markdown().splitlines():
                extra_notes.append(line)

    generated = datetime.now(timezone.utc).isoformat()
    markdown = verification_markdown(
        entity_name=result.entity_name,
        ticker=ticker,
        generated_at=generated,
        revenue=revenue_contrast,
        price=price_evidence,
        scenarios=report.scenarios,
        valuation_notes=report.valuation_notes,
        price_note=price_note,
        extra_notes=extra_notes,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")

    print(f"Empresa: {result.entity_name} ({ticker})")
    print(
        f"Ingresos {revenue_contrast.period_end.isoformat()}: "
        f"{revenue_contrast.summary()} "
        f"(SEC {revenue_contrast.primary_value:,.0f} "
        f"{revenue_contrast.primary_currency} vs "
        + (
            f"Nasdaq {revenue_contrast.aligned_secondary_value:,.0f} "
            if revenue_contrast.aligned_secondary_value is not None
            else "Nasdaq sin cifra "
        )
        + ")"
    )
    print(
        f"Nivel de la cifra primaria de ingresos: {revenue_obs.provenance_level.value} "
        f"· fuentes en el registro: {len(result.registry.sources)} "
        f"· observaciones: {len(result.registry.observations)}"
    )
    if price_evidence is None:
        print("Precio: sin dos fuentes coincidentes; no se calcula margen de seguridad")
    else:
        print(
            f"Precio {price_evidence.price_date.isoformat()}: {price_evidence.close:,.2f} "
            f"{price_evidence.currency} — {price_evidence.summary()}"
        )
    if report.scenarios:
        for scenario in report.scenarios:
            per_share = scenario.per_share_value
            mof = (
                f" · margen de seguridad {margin_of_safety(per_share, usable_price):.2%}"
                if per_share is not None and usable_price is not None
                and margin_of_safety(per_share, usable_price) is not None
                else ""
            )
            print(
                f"{scenario.scenario.name}: valor/acción "
                + (f"{per_share:,.2f} {scenario.currency}" if per_share is not None else "no calculable")
                + (f" · margen de subida {scenario.upside:+.2%}" if scenario.upside is not None else "")
                + mof
            )
    print(f"Informe de verificación escrito en: {output}")
    return 0


def primary_verify(args: argparse.Namespace) -> int:
    """Descarga el documento primario (HTML), extrae la cifra y la contrasta.

    Si la descarga, la validación o la identificación del documento fallan, se
    escribe el informe con estado `VERIFICACIÓN NO COMPLETADA` y el comando devuelve
    1. En ningún caso se usa el fixture local para simular una descarga real.
    """

    from nexo_invest.data.sec_edgar import (
        SecEdgarClient,
        SecEdgarError,
        companyfacts_fact_value,
        parse_primary_document,
    )
    from nexo_invest.verification import (
        ContrastStatus,
        contrast_failed,
        contrast_primary_document,
        primary_document_markdown,
    )

    period_start = date.fromisoformat(args.period_start)
    period_end = date.fromisoformat(args.period_end)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    client = SecEdgarClient(cache_dir=cache_dir)
    generated_at = datetime.now(timezone.utc).isoformat()
    entity_name = args.entity or args.ticker or "Empresa"

    def _write_and_finish(evidence, *, return_code: int, message: str) -> int:
        markdown = primary_document_markdown(
            entity_name=entity_name,
            ticker=args.ticker or "",
            generated_at=generated_at,
            evidence=evidence,
        )
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        print(message, file=sys.stderr)
        print(f"Informe escrito en: {output}", file=sys.stderr)
        return return_code

    try:
        client.require_contact("verificar el documento primario")
        raw, fetch = client.get_document(args.url, use_cache=not args.no_cache)
    except (SecEdgarError, ValueError) as exc:
        evidence = contrast_failed(
            metric=args.concept,
            period_end=period_end,
            primary_value=None,
            reason=f"{type(exc).__name__}: {exc}",
        )
        evidence.accession = args.accession
        return _write_and_finish(
            evidence,
            return_code=1,
            message=f"VERIFICACIÓN NO COMPLETADA (descarga): {exc}",
        )

    try:
        primary = parse_primary_document(
            raw,
            url=args.url,
            accession=args.accession,
            cik=args.cik,
            fetch=fetch,
            expected_form=args.form,
            expected_fiscal_year=args.fiscal_year,
        )
        fact = primary.annual_revenue(period_start=period_start, period_end=period_end)
        entity_name = primary.entity_name or entity_name
    except (SecEdgarError, ValueError) as exc:
        evidence = contrast_failed(
            metric=args.concept,
            period_end=period_end,
            primary_value=None,
            reason=f"{type(exc).__name__}: {exc}",
        )
        evidence.accession = args.accession
        evidence.content_sha256 = fetch.sha256 or None
        evidence.primary_url = args.url
        evidence.primary_retrieval = fetch.retrieved_at.date()
        kind = type(exc).__name__
        return _write_and_finish(
            evidence,
            return_code=1,
            message=f"VERIFICACIÓN NO COMPLETADA ({kind}): {exc}",
        )

    companyfacts_value = None
    companyfacts_retrieval = None
    companyfacts_error = None
    try:
        payload, cf_fetch = client.company_facts(primary.cik)
        companyfacts_value = companyfacts_fact_value(
            payload,
            concept=args.concept,
            period_start=period_start,
            period_end=period_end,
            form=args.form,
        )
        companyfacts_retrieval = cf_fetch.retrieved_at.date()
    except (SecEdgarError, ValueError) as exc:
        companyfacts_error = f"{type(exc).__name__}: {exc}"

    evidence = contrast_primary_document(
        period_start=period_start,
        period_end=period_end,
        html_value=fact.value,
        html_url=primary.url,
        html_retrieval=primary.retrieval_date,
        accession=primary.accession,
        content_sha256=primary.sha256,
        fiscal_year=primary.fiscal_year,
        fiscal_period=primary.fiscal_period,
        companyfacts_value=companyfacts_value,
        companyfacts_retrieval=companyfacts_retrieval,
        cik=primary.cik,
        concept=args.concept,
        form=args.form,
        html_from_cache=fetch.from_cache,
    )
    if companyfacts_error:
        evidence.reasons.append(
            f"CompanyFacts no pudo consultarse en esta ejecución: {companyfacts_error}"
        )

    markdown = primary_document_markdown(
        entity_name=entity_name,
        ticker=args.ticker or "",
        generated_at=generated_at,
        evidence=evidence,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")

    print(f"Entidad: {entity_name} (CIK {primary.cik})")
    print(
        f"Documento: {primary.form} · ejercicio {primary.fiscal_year} "
        f"{primary.fiscal_period or ''} · accession {primary.accession}"
    )
    print(f"SHA-256: {primary.sha256}")
    print(f"Valor extraído del HTML: {fact.value:,.0f} USD")
    if companyfacts_value is None:
        print("CompanyFacts: sin valor para ese periodo (contraste pendiente)")
    else:
        print(f"CompanyFacts: {companyfacts_value:,.0f} USD")
    print(f"Resultado: {evidence.summary()}")
    print(f"Informe escrito en: {output}")
    if evidence.status is ContrastStatus.INCOMPARABLE:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexo", description="Nexo Invest AI CLI")
    parser.add_argument("--version", action="store_true", help="Mostrar versión")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("version", help="Mostrar versión")
    p.set_defaults(func=version)

    pm = sub.add_parser("metrics-demo", help="Demo con datos locales")
    pm.set_defaults(func=metrics_demo)

    ps = sub.add_parser(
        "sec-report",
        help="Descargar una empresa real de SEC EDGAR y generar su informe Markdown",
    )
    ps.add_argument("--ticker", help="Ticker de la empresa (se resuelve a CIK con el fichero oficial)")
    ps.add_argument("--cik", type=int, help="CIK de la SEC (alternativa al ticker)")
    ps.add_argument("--out", required=True, help="Ruta del informe Markdown de salida")
    ps.add_argument("--cache-dir", help="Carpeta de caché para no repetir descargas")
    ps.add_argument("--max-annual-periods", type=int, default=None,
                    help="Limitar el número de cierres anuales registrados")
    ps.add_argument("--forecast-years", type=int, default=5, help="Años proyectados en el DCF")
    ps.add_argument("--share-price", type=float, default=None,
                    help="Precio de mercado verificado (opcional). Sin él no se calcula margen de subida")
    ps.set_defaults(func=sec_report)

    psc = sub.add_parser(
        "screen",
        help="Aplicar la estrategia de valor a varias empresas reales de SEC EDGAR",
    )
    psc.add_argument("--tickers", required=True, help="Lista de tickers separada por comas")
    psc.add_argument("--out", required=True, help="Ruta del informe Markdown de salida")
    psc.add_argument("--cache-dir", help="Carpeta de caché para no repetir descargas")
    psc.set_defaults(func=screen)

    pb = sub.add_parser(
        "backtest",
        help="Prueba histórica exploratoria de una regla de momento sobre precios reales",
    )
    pb.add_argument("--symbol", default="AAPL", help="Ticker del activo")
    pb.add_argument("--out", required=True, help="Ruta del informe Markdown de salida")
    pb.add_argument("--cache-dir", help="Carpeta de caché de precios")
    pb.add_argument("--fixture", help="Usar una serie local en lugar de descargarla")
    pb.add_argument("--years-range", default="5y", help="Rango solicitado a la fuente (ej. 5y, 10y)")
    pb.add_argument("--label", default="momento 12 meses, rebalanceo mensual")
    pb.add_argument("--lookback", type=int, default=252, help="Sesiones de la ventana de momento")
    pb.add_argument("--rebalance", type=int, default=21, help="Sesiones entre rebalanceos")
    pb.add_argument("--commission", type=float, default=0.0010, help="Comisión por operación (fracción)")
    pb.add_argument("--slippage", type=float, default=0.0005, help="Deslizamiento (fracción)")
    pb.set_defaults(func=backtest)

    pv = sub.add_parser(
        "verify",
        help="Contrasta ingresos y precio con una segunda fuente y valora con el precio comprobado",
    )
    pv.add_argument("--ticker", default="AAPL", help="Ticker de la empresa")
    pv.add_argument("--out", required=True, help="Ruta del informe Markdown de salida")
    pv.add_argument("--cache-dir", help="Carpeta de caché para no repetir descargas")
    pv.add_argument("--forecast-years", type=int, default=5, help="Años proyectados en el DCF")
    pv.add_argument("--price-date", help="Fecha de negociación a comprobar (AAAA-MM-DD)")
    pv.add_argument("--price-range", default="6mo", help="Rango de la serie de precios")
    pv.add_argument("--nasdaq-financials-fixture", help="Fixture local de la fuente secundaria")
    pv.add_argument("--nasdaq-history-fixture", help="Fixture local de cierres de la segunda fuente")
    pv.add_argument("--price-fixture", help="Fixture local de la serie de precios")
    pv.add_argument("--backtest-fixture", help="Serie para revisar la prueba histórica")
    pv.set_defaults(func=verify)

    pp = sub.add_parser(
        "primary-verify",
        help="Descarga el documento primario en HTML, extrae la cifra y la contrasta "
        "con SEC CompanyFacts",
    )
    pp.add_argument("--ticker", default="AAPL", help="Ticker de la empresa")
    pp.add_argument("--entity", help="Nombre de la entidad para el informe")
    pp.add_argument("--cik", type=int, required=True, help="CIK de la SEC")
    pp.add_argument("--accession", required=True, help="Accession number del documento")
    pp.add_argument("--url", required=True, help="URL del documento HTML en EDGAR")
    pp.add_argument("--form", default="10-K", help="Formulario esperado (por defecto 10-K)")
    pp.add_argument("--fiscal-year", type=int, required=True, help="Ejercicio fiscal esperado")
    pp.add_argument("--period-start", required=True, help="Inicio del periodo (AAAA-MM-DD)")
    pp.add_argument("--period-end", required=True, help="Fin del periodo (AAAA-MM-DD)")
    pp.add_argument(
        "--concept",
        default="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        help="Concepto XBRL a extraer",
    )
    pp.add_argument("--out", required=True, help="Ruta del informe Markdown de salida")
    pp.add_argument("--cache-dir", help="Carpeta de caché para no repetir descargas")
    pp.add_argument(
        "--no-cache",
        action="store_true",
        help="Fuerza una descarga nueva en lugar de leer la caché local",
    )
    pp.set_defaults(func=primary_verify)

    args = parser.parse_args(argv)
    if args.version or args.command is None:
        version(args)
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
