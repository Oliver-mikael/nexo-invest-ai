import { useEffect, useState } from "react"
import { ApiError, portfolioApi, type PortfolioSummary } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Field, Notice, SectionHeader, Stat, Table } from "../components/ui"
import { money, pct } from "../lib/format"

export function Portfolio() {
  const list = useAsync(() => portfolioApi.list(), [])
  const [selected, setSelected] = useState<number | null>(null)
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ symbol: "", side: "buy", quantity: "1", price: "", thesis: "" })
  const [createForm, setCreateForm] = useState({ name: "Mi cartera", starting_cash: "100000", benchmark: "SPY" })

  useEffect(() => {
    if (selected === null && list.data?.items.length) {
      setSelected(list.data.items[0].id)
    }
  }, [list.data, selected])

  useEffect(() => {
    if (selected === null) return
    let active = true
    portfolioApi
      .get(selected)
      .then((data) => {
        if (active) setSummary(data)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "No se pudo cargar la cartera")
      })
    return () => {
      active = false
    }
  }, [selected])

  const create = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await portfolioApi.create({
        name: createForm.name,
        starting_cash: Number(createForm.starting_cash),
        benchmark: createForm.benchmark,
      })
      setSelected(created.id)
      list.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la cartera")
    } finally {
      setBusy(false)
    }
  }

  const trade = async (event: React.FormEvent) => {
    event.preventDefault()
    if (selected === null) return
    setBusy(true)
    setError(null)
    try {
      await portfolioApi.trade(selected, {
        symbol: form.symbol.toUpperCase(),
        side: form.side,
        quantity: Number(form.quantity),
        price: Number(form.price),
        thesis: form.thesis,
      })
      const updated = await portfolioApi.get(selected)
      setSummary(updated)
      setForm({ ...form, symbol: "", price: "", thesis: "" })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo registrar la operación")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Simulación</p>
          <h1 className="mt-1 font-display text-4xl tracking-tight">Cartera</h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-500">
            Compras y ventas ficticias para contrastar tesis con resultados. Sin dinero real ni
            conexión con brókers.
          </p>
        </div>
        {list.data && list.data.items.length > 1 ? (
          <select
            className="field max-w-[220px]"
            value={selected ?? ""}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {list.data.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {error ? <ErrorNotice message={error} /> : null}
      {list.error ? <ErrorNotice message={list.error} onRetry={list.reload} /> : null}

      {list.data && list.data.items.length === 0 ? (
        <Card>
          <SectionHeader
            title="Crear cartera"
            subtitle="El efectivo inicial es ficticio. Puedes crear varias carteras."
          />
          <form className="grid gap-3 sm:grid-cols-3" onSubmit={create}>
            <Field label="Nombre">
              <input
                className="field"
                value={createForm.name}
                onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                maxLength={120}
              />
            </Field>
            <Field label="Efectivo inicial">
              <input
                className="field"
                type="number"
                min="100"
                step="1000"
                value={createForm.starting_cash}
                onChange={(event) => setCreateForm({ ...createForm, starting_cash: event.target.value })}
              />
            </Field>
            <Field label="Benchmark">
              <input
                className="field font-mono uppercase"
                value={createForm.benchmark}
                onChange={(event) => setCreateForm({ ...createForm, benchmark: event.target.value })}
                maxLength={16}
              />
            </Field>
            <div className="sm:col-span-3">
              <button type="submit" className="btn-primary" disabled={busy}>
                Crear cartera
              </button>
            </div>
          </form>
        </Card>
      ) : null}

      {summary ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Valor total" value={money(summary.total_value, summary.currency)} hint={`Efectivo ${money(summary.cash, summary.currency)}`} />
            <Stat
              label="Rentabilidad"
              value={pct(summary.total_return)}
              tone={(summary.total_return ?? 0) >= 0 ? "good" : "warn"}
              hint={`Desde ${money(summary.starting_cash, summary.currency)}`}
            />
            <Stat
              label="Beneficio realizado"
              value={money(summary.realized_pnl, summary.currency)}
              hint={`No realizado ${money(summary.unrealized_pnl, summary.currency)}`}
            />
            <Stat
              label={`Benchmark ${summary.benchmark.symbol}`}
              value={summary.benchmark.return == null ? "—" : pct(summary.benchmark.return)}
              hint={`Precios: ${summary.prices_source}`}
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
            <Card>
              <SectionHeader
                title="Posiciones"
                subtitle={`${summary.priced_positions}/${summary.total_positions} valoradas con precio de mercado.`}
              />
              {summary.positions.length === 0 ? (
                <p className="text-sm text-ink-500">Sin posiciones todavía.</p>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <th>Símbolo</th>
                      <th className="text-right">Cantidad</th>
                      <th className="text-right">Coste medio</th>
                      <th className="text-right">Precio</th>
                      <th className="text-right">Valor</th>
                      <th className="text-right">No realizado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.positions.map((position) => (
                      <tr key={position.symbol}>
                        <td className="font-mono">{position.symbol}</td>
                        <td className="text-right font-mono">{position.quantity}</td>
                        <td className="text-right font-mono">{position.avg_cost.toFixed(2)}</td>
                        <td className="text-right font-mono">
                          {position.price != null ? position.price.toFixed(2) : <Badge tone="muted">sin precio</Badge>}
                        </td>
                        <td className="text-right font-mono">{money(position.market_value, summary.currency)}</td>
                        <td className={`text-right font-mono ${(position.unrealized ?? 0) >= 0 ? "text-moss-600" : "text-rust-600"}`}>
                          {position.unrealized == null ? "—" : money(position.unrealized, summary.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
              <p className="mt-3 text-xs leading-relaxed text-ink-300">
                Las posiciones sin precio se valoran a coste y se marcan como no valoradas: no se
                inventa una cotización.
              </p>
            </Card>

            <Card>
              <SectionHeader title="Registrar operación" />
              <form className="space-y-3" onSubmit={trade}>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Símbolo">
                    <input
                      className="field font-mono uppercase"
                      value={form.symbol}
                      onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })}
                      required
                      maxLength={12}
                    />
                  </Field>
                  <Field label="Lado">
                    <select
                      className="field"
                      value={form.side}
                      onChange={(event) => setForm({ ...form, side: event.target.value })}
                    >
                      <option value="buy">Compra</option>
                      <option value="sell">Venta</option>
                    </select>
                  </Field>
                  <Field label="Cantidad">
                    <input
                      className="field"
                      type="number"
                      min="0.0001"
                      step="any"
                      value={form.quantity}
                      onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                      required
                    />
                  </Field>
                  <Field label="Precio">
                    <input
                      className="field"
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={form.price}
                      onChange={(event) => setForm({ ...form, price: event.target.value })}
                      required
                    />
                  </Field>
                </div>
                <Field label="Tesis (opcional)" hint="Se guarda con la posición para comparar después.">
                  <textarea
                    className="field min-h-[70px]"
                    value={form.thesis}
                    onChange={(event) => setForm({ ...form, thesis: event.target.value })}
                    maxLength={4000}
                  />
                </Field>
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy ? "Registrando…" : "Registrar operación"}
                </button>
              </form>
            </Card>
          </div>

          <Notice tone="info">{summary.warning}</Notice>
        </>
      ) : null}
    </div>
  )
}
