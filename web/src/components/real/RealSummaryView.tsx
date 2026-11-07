import { useState } from "react"
import { ApiError, marketsApi, type Instrument, type Market, type RealSummary } from "../../lib/api"
import { moneyString, pctRaw, qualityLabel, shortDate } from "../../lib/format"
import { Badge, Card, Field, Notice, SectionHeader, Stat, Table } from "../ui"

function Distribution({
  title,
  values,
  currency,
}: {
  title: string
  values: Record<string, string>
  currency: string
}) {
  const entries = Object.entries(values).filter(([, value]) => Number(value) > 0)
  const max = Math.max(...entries.map(([, value]) => Number(value)), 1)
  if (!entries.length) return null
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">{title}</p>
      <div className="mt-2 space-y-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="font-mono text-ink-700">{key}</span>
              <span className="text-ink-500">{moneyString(value, currency)}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-900/10">
              <div
                className="h-full rounded-full bg-moss-500"
                style={{ width: `${Math.max(3, (Number(value) / max) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function RealSummaryView({
  summary,
  instruments,
  markets,
  onChanged,
}: {
  summary: RealSummary
  instruments: Instrument[]
  markets: Market[]
  onChanged: () => void
}) {
  const [quote, setQuote] = useState({
    uid: instruments[0]?.uid ?? "",
    price: "",
    as_of: new Date().toISOString().slice(0, 10),
    quality: "close",
    source: "manual",
  })
  const [instrument, setInstrument] = useState({
    symbol: "",
    name: "",
    market_code: markets[0]?.code ?? "XNAS",
    currency: markets[0]?.currency ?? "USD",
    instrument_type: "stock",
  })
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const currency = summary.base_currency

  const addQuote = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setOk(null)
    try {
      if (!quote.uid) throw new Error("Selecciona un instrumento.")
      await marketsApi.quote(quote.uid, {
        price: quote.price,
        as_of: quote.as_of,
        source: quote.source,
        quality: quote.quality,
      })
      setOk("Cotización registrada con fuente y fecha del dato.")
      setQuote({ ...quote, price: "" })
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "No se pudo guardar")
    }
  }

  const addInstrument = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setOk(null)
    try {
      await marketsApi.createInstrument(instrument)
      setOk(`Instrumento ${instrument.symbol.toUpperCase()} creado.`)
      setInstrument({ ...instrument, symbol: "", name: "" })
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "No se pudo crear")
    }
  }

  const totals = summary.positions.reduce<Record<string, number>>((acc, position) => {
    acc[position.market || "—"] = (acc[position.market || "—"] ?? 0) + Number(position.market_value_base ?? 0)
    return acc
  }, {})
  const byCountry = summary.positions.reduce<Record<string, number>>((acc, position) => {
    acc[position.country_code || "—"] = (acc[position.country_code || "—"] ?? 0) + Number(position.market_value_base ?? 0)
    return acc
  }, {})
  const byCurrency = summary.positions.reduce<Record<string, number>>((acc, position) => {
    acc[position.currency] = (acc[position.currency] ?? 0) + Number(position.market_value_base ?? 0)
    return acc
  }, {})
  const byMarket = Object.fromEntries(Object.entries(totals).map(([key, value]) => [key, String(value)]))

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Valor actual"
          value={summary.total_value_base ? moneyString(summary.total_value_base, currency) : "Sin valorar"}
          tone={summary.complete ? "default" : "warn"}
          hint={`Efectivo ${moneyString(summary.cash_base, currency)} · ${summary.positions.length} posición(es)`}
        />
        <Stat
          label="Capital aportado neto"
          value={moneyString(summary.net_contributions_base, currency)}
          hint="Depósitos − retiros ± traspasos y ajustes de conciliación."
        />
        <Stat
          label="Ganancia neta"
          value={summary.net_gain_base ? moneyString(summary.net_gain_base, currency) : "—"}
          tone={Number(summary.net_gain_base ?? 0) >= 0 ? "good" : "warn"}
          hint={`Realizada ${moneyString(summary.realized_base, currency)} · no realizada ${moneyString(summary.unrealized_base, currency)}`}
        />
        <Stat
          label="Rentabilidad"
          value={summary.xirr_pct ? `XIRR ${pctRaw(summary.xirr_pct)}` : "XIRR —"}
          tone={Number(summary.xirr_pct ?? 0) >= 0 ? "good" : "warn"}
          hint={
            summary.twr_available
              ? `TWR ${pctRaw(summary.twr_pct)}`
              : `TWR no disponible: ${summary.twr_reason || "faltan datos"}`
          }
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Dividendos netos" value={moneyString(summary.dividends_base, currency)} hint="Brutos menos retenciones." />
        <Stat label="Comisiones sueltas" value={moneyString(summary.other_fees_base, currency)} hint="Las comisiones de compra se capitalizan en el coste." />
        <Stat label="Impuestos sueltos" value={moneyString(summary.other_taxes_base, currency)} hint="Retenciones y tasas no ligadas a una venta." />
        <Stat label="Método contable" value={summary.cost_method === "fifo" ? "FIFO" : "Coste medio"} hint="El otro método se conserva para comparación en el motor." />
      </div>

      {!summary.complete ? (
        <Notice tone="warning">
          Valoración incompleta: faltan cotizaciones o tipos de cambio. No se ha inventado ninguna
          cifra. Añade una cotización con su fuente y fecha, o registra el tipo de cambio histórico.
          {summary.missing_prices.length ? ` Instrumentos sin precio: ${summary.missing_prices.length}.` : ""}
          {summary.missing_fx.length ? ` Divisas sin cambio: ${summary.missing_fx.join(", ")}.` : ""}
        </Notice>
      ) : null}
      {summary.data_errors.length ? (
        <Notice tone="error">
          Hay movimientos que no se pudieron interpretar: {summary.data_errors.slice(0, 3).join(" · ")}
        </Notice>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1.55fr_1fr]">
        <Card>
          <SectionHeader
            title="Posiciones"
            subtitle="Cada valor se calcula en el backend con Decimal y conserva la fuente del precio."
          />
          {summary.positions.length === 0 ? (
            <p className="rounded-lg border border-dashed border-ink-900/15 p-5 text-sm text-ink-500">
              Sin posiciones abiertas. Registra una compra en Movimientos.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Instrumento</th>
                  <th className="text-right">Cantidad</th>
                  <th className="text-right">Coste</th>
                  <th className="text-right">Precio</th>
                  <th className="text-right">Valor</th>
                  <th className="text-right">No realizado</th>
                  <th className="text-right">Efecto FX</th>
                </tr>
              </thead>
              <tbody>
                {summary.positions.map((position) => (
                  <tr key={position.instrument_uid}>
                    <td>
                      <p className="font-mono text-sm font-medium text-ink-900">{position.symbol}</p>
                      <p className="text-[11px] text-ink-300">
                        {position.market} · {position.currency} · {position.name || position.instrument_type}
                      </p>
                    </td>
                    <td className="text-right font-mono">{Number(position.quantity).toLocaleString("es-ES")}</td>
                    <td className="text-right font-mono">{moneyString(position.cost_base, currency)}</td>
                    <td className="text-right font-mono">
                      {position.price ? (
                        <>
                          <p>{moneyString(position.price, position.currency)}</p>
                          <p className="text-[10px] text-ink-300">
                            {position.quote_source || "sin fuente"} · {shortDate(position.quote_as_of)}
                          </p>
                          <Badge tone={qualityLabel(position.quote_quality).tone}>
                            {qualityLabel(position.quote_quality).text}
                          </Badge>
                        </>
                      ) : (
                        <Badge tone="warn">sin precio</Badge>
                      )}
                    </td>
                    <td className="text-right font-mono">
                      {position.market_value_base ? moneyString(position.market_value_base, currency) : "—"}
                    </td>
                    <td
                      className={`text-right font-mono ${
                        Number(position.unrealized_base ?? 0) >= 0 ? "text-moss-600" : "text-rust-600"
                      }`}
                    >
                      {position.unrealized_base ? moneyString(position.unrealized_base, currency) : "—"}
                    </td>
                    <td className="text-right font-mono text-ink-500">
                      {position.fx_effect_base ? moneyString(position.fx_effect_base, currency) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
            El efecto cambiario separa la revalorización del activo de la divisa. Una posición sin
            cotización se muestra sin valorar y no se suma a los totales.
          </p>
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionHeader title="Distribución" subtitle="Solo posiciones valoradas, en moneda base." />
            <div className="space-y-4">
              <Distribution title="Por mercado" values={byMarket} currency={currency} />
              <Distribution
                title="Por país"
                values={Object.fromEntries(Object.entries(byCountry).map(([k, v]) => [k, String(v)]))}
                currency={currency}
              />
              <Distribution
                title="Por divisa del activo"
                values={Object.fromEntries(Object.entries(byCurrency).map(([k, v]) => [k, String(v)]))}
                currency={currency}
              />
            </div>
          </Card>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader
            title="Añadir cotización"
            subtitle="Sin proveedor automático, el precio se registra con fuente y fecha. No se presenta como tiempo real si no lo es."
          />
          <form className="space-y-3" onSubmit={addQuote}>
            <Field label="Instrumento">
              <select className="field" value={quote.uid} onChange={(event) => setQuote({ ...quote, uid: event.target.value })}>
                <option value="">Selecciona…</option>
                {instruments.map((item) => (
                  <option key={item.uid} value={item.uid}>
                    {item.symbol} · {item.market}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Precio">
                <input
                  className="field font-mono"
                  inputMode="decimal"
                  value={quote.price}
                  onChange={(event) => setQuote({ ...quote, price: event.target.value })}
                  required
                />
              </Field>
              <Field label="Fecha del dato">
                <input
                  className="field"
                  type="date"
                  value={quote.as_of}
                  onChange={(event) => setQuote({ ...quote, as_of: event.target.value })}
                  required
                />
              </Field>
              <Field label="Fuente">
                <input
                  className="field"
                  value={quote.source}
                  onChange={(event) => setQuote({ ...quote, source: event.target.value })}
                  required
                />
              </Field>
              <Field label="Calidad">
                <select
                  className="field"
                  value={quote.quality}
                  onChange={(event) => setQuote({ ...quote, quality: event.target.value })}
                >
                  <option value="close">Último cierre</option>
                  <option value="delayed">Retrasado</option>
                  <option value="realtime">Tiempo real</option>
                  <option value="historical">Histórico</option>
                  <option value="estimated">Estimado</option>
                </select>
              </Field>
            </div>
            <button type="submit" className="btn-primary w-full">
              Guardar cotización
            </button>
          </form>
        </Card>

        <Card>
          <SectionHeader
            title="Nuevo instrumento"
            subtitle="Identidad por mercado + símbolo, con ISIN cuando exista. El ticker no es único global."
          />
          <form className="space-y-3" onSubmit={addInstrument}>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Símbolo">
                <input
                  className="field font-mono uppercase"
                  value={instrument.symbol}
                  onChange={(event) => setInstrument({ ...instrument, symbol: event.target.value.toUpperCase() })}
                  required
                  maxLength={32}
                />
              </Field>
              <Field label="Mercado">
                <select
                  className="field"
                  value={instrument.market_code}
                  onChange={(event) => {
                    const selected = markets.find((item) => item.code === event.target.value)
                    setInstrument({
                      ...instrument,
                      market_code: event.target.value,
                      currency: selected?.currency ?? instrument.currency,
                    })
                  }}
                >
                  {markets.map((market) => (
                    <option key={market.code} value={market.code}>
                      {market.code} · {market.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Nombre">
              <input
                className="field"
                value={instrument.name}
                onChange={(event) => setInstrument({ ...instrument, name: event.target.value })}
                maxLength={255}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Moneda">
                <input
                  className="field font-mono uppercase"
                  value={instrument.currency}
                  onChange={(event) => setInstrument({ ...instrument, currency: event.target.value.toUpperCase() })}
                  maxLength={3}
                  required
                />
              </Field>
              <Field label="Tipo">
                <select
                  className="field"
                  value={instrument.instrument_type}
                  onChange={(event) => setInstrument({ ...instrument, instrument_type: event.target.value })}
                >
                  <option value="stock">Acción</option>
                  <option value="etf">ETF</option>
                  <option value="index">Índice</option>
                  <option value="fund">Fondo</option>
                  <option value="bond">Bono</option>
                  <option value="reit">REIT</option>
                  <option value="crypto">Cripto</option>
                  <option value="other">Otro</option>
                </select>
              </Field>
            </div>
            <button type="submit" className="btn-ghost w-full">
              Crear instrumento
            </button>
          </form>
        </Card>
      </div>

      {error ? <p className="text-sm text-rust-600">{error}</p> : null}
      {ok ? <p className="text-sm text-moss-600">{ok}</p> : null}
    </div>
  )
}
