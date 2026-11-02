import { useState } from "react"
import { backtestsApi, boardApi, marketsApi, type BacktestRun } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { LineChart } from "../components/charts"
import { Badge, Card, EmptyState, ErrorNotice, Field, Notice, SectionHeader, Spinner, Table } from "../components/ui"

const pct = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(2)} %`)
const num = (value: number | null) => (value === null ? "—" : value.toFixed(2))

export function Backtests() {
  const runs = useAsync(() => backtestsApi.list(), [])
  const [selected, setSelected] = useState<number | null>(null)
  const [created, setCreated] = useState<BacktestRun | null>(null)

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Validación</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Backtests</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Simulación determinista sobre cierres con procedencia: costes, slippage, divisas históricas
          y walk-forward. El pasado describe; no garantiza.
        </p>
      </div>

      <NewBacktestForm
        onDone={(run) => {
          setCreated(run)
          setSelected(run.id)
          runs.reload()
        }}
      />

      {created ? (
        <Notice tone="success">
          Backtest #{created.id} ejecutado: {created.trades} operaciones, rentabilidad{" "}
          {pct(created.metrics.total_return)} en {created.points} cierres.
        </Notice>
      ) : null}
      {runs.error ? <ErrorNotice message={runs.error} onRetry={runs.reload} /> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <SectionHeader title="Historial" subtitle={`${runs.data?.items.length ?? 0} ejecuciones`} />
          {runs.loading && !runs.data ? (
            <Spinner />
          ) : (runs.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="Sin backtests"
              description="Ejecuta una simulación con los parámetros que quieras validar."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Instrumento</th>
                  <th>Estrategia</th>
                  <th>Retorno</th>
                  <th>Período</th>
                </tr>
              </thead>
              <tbody>
                {(runs.data?.items ?? []).map((run) => (
                  <tr
                    key={run.id}
                    className={`cursor-pointer ${selected === run.id ? "bg-ink-900/5" : ""}`}
                    onClick={() => setSelected(run.id)}
                  >
                    <td className="font-mono text-xs">{run.id}</td>
                    <td className="font-mono text-xs font-semibold">{run.instrument.symbol ?? "—"}</td>
                    <td className="text-xs">
                      {run.strategy}
                      {run.walk_forward.applied ? " · wf" : ""}
                    </td>
                    <td className="font-mono text-xs">{pct(run.metrics.total_return)}</td>
                    <td className="font-mono text-[11px] text-ink-500">
                      {run.period_start} → {run.period_end}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        {selected === null ? (
          <Card>
            <EmptyState
              title="Selecciona un backtest"
              description="Verás métricas, curva de equity, operaciones, advertencias y la comparación con el benchmark."
            />
          </Card>
        ) : (
          <BacktestDetail key={selected} id={selected} />
        )}
      </div>
    </div>
  )
}

function NewBacktestForm({ onDone }: { onDone: (run: BacktestRun) => void }) {
  const watchlist = useAsync(() => boardApi.watchlist(), [])
  const instruments = useAsync(() => marketsApi.instruments("", ""), [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    instrument_uid: "",
    benchmark_uid: "",
    strategy: "buy_hold",
    fast: "10",
    slow: "50",
    base_currency: "USD",
    initial_cash: "10000",
    commission_bps: "5",
    slippage_bps: "5",
    walk_forward: false,
  })

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const run = await backtestsApi.create({
        instrument_uid: form.instrument_uid,
        strategy: form.strategy,
        params: form.strategy === "sma_cross" ? { fast: Number(form.fast), slow: Number(form.slow) } : {},
        base_currency: form.base_currency,
        initial_cash: form.initial_cash,
        commission_bps: form.commission_bps,
        slippage_bps: form.slippage_bps,
        benchmark_uid: form.benchmark_uid || null,
        walk_forward: form.walk_forward,
      })
      onDone(run)
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo ejecutar el backtest")
    } finally {
      setBusy(false)
    }
  }

  const options = (instruments.data?.items ?? []).length
    ? instruments.data!.items
    : (watchlist.data?.items ?? []).map((item) => ({
        uid: item.instrument_uid,
        symbol: item.symbol,
        name: item.name,
      }))

  return (
    <Card>
      <SectionHeader
        title="Nueva simulación"
        subtitle="Señales al cierre, ejecución al cierre del día siguiente (sin look-ahead)."
      />
      {error ? <Notice tone="error">{error}</Notice> : null}
      <form className="grid gap-4 md:grid-cols-3" onSubmit={submit}>
        <Field label="Instrumento">
          <select
            className="field"
            value={form.instrument_uid}
            onChange={(event) => setForm({ ...form, instrument_uid: event.target.value })}
            required
          >
            <option value="">Elige uno…</option>
            {options.map((item) => (
              <option key={item.uid} value={item.uid}>
                {item.symbol} — {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Benchmark (opcional)">
          <select
            className="field"
            value={form.benchmark_uid}
            onChange={(event) => setForm({ ...form, benchmark_uid: event.target.value })}
          >
            <option value="">Sin benchmark</option>
            {options.map((item) => (
              <option key={item.uid} value={item.uid}>
                {item.symbol}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Estrategia">
          <select
            className="field"
            value={form.strategy}
            onChange={(event) => setForm({ ...form, strategy: event.target.value })}
          >
            <option value="buy_hold">Comprar y mantener</option>
            <option value="sma_cross">Cruce de medias SMA</option>
          </select>
        </Field>
        {form.strategy === "sma_cross" ? (
          <>
            <Field label="Ventana rápida">
              <input
                className="field"
                type="number"
                min="2"
                value={form.fast}
                onChange={(event) => setForm({ ...form, fast: event.target.value })}
              />
            </Field>
            <Field label="Ventana lenta">
              <input
                className="field"
                type="number"
                min="3"
                value={form.slow}
                onChange={(event) => setForm({ ...form, slow: event.target.value })}
              />
            </Field>
            <Field label="Walk-forward" hint="Elige parámetros en el 60 % inicial y evalúa en el resto.">
              <label className="flex h-10 items-center gap-2 text-sm text-ink-600">
                <input
                  type="checkbox"
                  checked={form.walk_forward}
                  onChange={(event) => setForm({ ...form, walk_forward: event.target.checked })}
                />
                Separar entrenamiento y evaluación
              </label>
            </Field>
          </>
        ) : null}
        <Field label="Moneda base">
          <input
            className="field"
            maxLength={3}
            value={form.base_currency}
            onChange={(event) => setForm({ ...form, base_currency: event.target.value.toUpperCase() })}
          />
        </Field>
        <Field label="Capital inicial">
          <input
            className="field"
            type="number"
            min="1"
            step="any"
            value={form.initial_cash}
            onChange={(event) => setForm({ ...form, initial_cash: event.target.value })}
          />
        </Field>
        <Field label="Comisión (pb por operación)">
          <input
            className="field"
            type="number"
            min="0"
            max="1000"
            value={form.commission_bps}
            onChange={(event) => setForm({ ...form, commission_bps: event.target.value })}
          />
        </Field>
        <Field label="Slippage (pb)">
          <input
            className="field"
            type="number"
            min="0"
            max="1000"
            value={form.slippage_bps}
            onChange={(event) => setForm({ ...form, slippage_bps: event.target.value })}
          />
        </Field>
        <div className="flex items-end">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Simulando…" : "Ejecutar backtest"}
          </button>
        </div>
      </form>
    </Card>
  )
}

function BacktestDetail({ id }: { id: number }) {
  const detail = useAsync(() => backtestsApi.get(id), [id])

  if (detail.error) return <ErrorNotice message={detail.error} onRetry={detail.reload} />
  const run = detail.data
  if (!run) return <Card><Spinner /></Card>

  const curve = (run.curve ?? []).map((point) => ({
    label: point.date.slice(5),
    value: Number(point.equity),
  }))

  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader
          title={`${run.instrument.symbol ?? "—"} · ${run.strategy}`}
          subtitle={`${run.period_start} → ${run.period_end} · ${run.points} cierres · ${run.base_currency}`}
          action={<Badge tone="muted">{run.walk_forward.applied ? "walk-forward" : "estático"}</Badge>}
        />
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Metric label="Rentabilidad total" value={pct(run.metrics.total_return)} />
          <Metric label="CAGR" value={pct(run.metrics.cagr)} />
          <Metric label="Volatilidad anual" value={pct(run.metrics.ann_volatility)} />
          <Metric label="Máx. drawdown" value={pct(run.metrics.max_drawdown)} />
          <Metric label="Sharpe" value={num(run.metrics.sharpe)} />
          <Metric label="Sortino" value={num(run.metrics.sortino)} />
          <Metric label="Operaciones" value={String(run.trades)} />
          <Metric label="Equity final" value={run.metrics.final_equity} />
        </div>

        {curve.length > 1 ? (
          <div className="mt-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
              Curva de equity ({run.base_currency})
            </p>
            <LineChart points={curve} format={(value) => value.toLocaleString("es")} />
          </div>
        ) : null}

        {run.walk_forward.applied ? (
          <Notice tone="info">
            Walk-forward: {run.walk_forward.train_points} cierres de entrenamiento,{" "}
            {run.walk_forward.eval_points} de evaluación; parámetros elegidos{" "}
            {JSON.stringify(run.walk_forward.chosen)}. {run.walk_forward.note}
          </Notice>
        ) : run.walk_forward.reason ? (
          <Notice>{run.walk_forward.reason}</Notice>
        ) : null}

        {run.benchmark_result?.available ? (
          <div className="mt-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
              Benchmark {run.benchmark_result.symbol}
            </p>
            <p className="mt-1 font-mono text-sm text-ink-600">
              retorno {pct(run.benchmark_result.metrics!.total_return)} · CAGR{" "}
              {pct(run.benchmark_result.metrics!.cagr)} · máx. drawdown{" "}
              {pct(run.benchmark_result.metrics!.max_drawdown)}
            </p>
          </div>
        ) : null}

        {(run.warnings ?? []).length > 0 ? (
          <div className="mt-4 space-y-2">
            {run.warnings.map((warning, index) => (
              <Notice tone="warning" key={index}>
                {warning}
              </Notice>
            ))}
          </div>
        ) : null}
        {(run.notes ?? []).map((note, index) => (
          <p key={index} className="mt-2 text-xs leading-relaxed text-ink-400">
            {note}
          </p>
        ))}
      </Card>

      {(run.last_trades ?? []).length > 0 ? (
        <Card>
          <SectionHeader title="Últimas operaciones" subtitle="Ejecutadas al cierre del día siguiente a la señal." />
          <Table>
            <thead>
              <tr>
                <th>Día</th>
                <th>Lado</th>
                <th>Precio</th>
                <th>Cantidad</th>
                <th>Comisión</th>
              </tr>
            </thead>
            <tbody>
              {(run.last_trades ?? []).map((trade, index) => (
                <tr key={`${trade.day}-${index}`}>
                  <td className="font-mono text-xs">{trade.day}</td>
                  <td>
                    <Badge tone={trade.side === "buy" ? "fact" : "warn"}>
                      {trade.side === "buy" ? "compra" : "venta"}
                    </Badge>
                  </td>
                  <td className="font-mono text-xs">{trade.price}</td>
                  <td className="font-mono text-xs">{trade.qty}</td>
                  <td className="font-mono text-xs">{trade.fee}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-500">{label}</p>
      <p className="mt-1 font-mono text-base font-semibold text-ink-900">{value}</p>
    </div>
  )
}
