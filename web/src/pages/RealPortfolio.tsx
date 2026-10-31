import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { ApiError, marketsApi, realApi, type RealMovement, type RealOverview, type RealSummary } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { moneyString, pctRaw, shortDate } from "../lib/format"
import { Badge, Card, ErrorNotice, Field, Notice, SectionHeader, Table, Tabs } from "../components/ui"
import { RealSummaryView } from "../components/real/RealSummaryView"
import { MovementForm } from "../components/real/MovementForm"
import { ImportPanel } from "../components/real/ImportPanel"
import { DocumentsPanel } from "../components/real/DocumentsPanel"

type Tab = "resumen" | "movimientos" | "importar" | "documentos"

const TYPE_LABELS: Record<string, string> = {
  deposit: "Depósito",
  withdrawal: "Retiro",
  buy: "Compra",
  sell: "Venta",
  dividend: "Dividendo",
  fee: "Comisión",
  tax: "Impuesto",
  adjustment: "Ajuste",
  split: "Split",
  transfer_in: "Traspaso entrada",
  transfer_out: "Traspaso salida",
}

export function RealPortfolio() {
  const [version, setVersion] = useState(0)
  const overview = useAsync<RealOverview>(() => realApi.overview(), [version])
  const markets = useAsync(() => marketsApi.list(), [])
  const instrumentList = useAsync(() => marketsApi.instruments("", ""), [version])
  const [selected, setSelected] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>("resumen")
  const [summary, setSummary] = useState<RealSummary | null>(null)
  const [movements, setMovements] = useState<RealMovement[]>([])
  const [loadingAccount, setLoadingAccount] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAccountForm, setShowAccountForm] = useState(false)
  const [accountForm, setAccountForm] = useState({
    name: "Cuenta principal",
    broker_name: "",
    broker_country: "",
    base_currency: "USD",
    cost_method: "fifo",
  })
  const [accountBusy, setAccountBusy] = useState(false)

  const accounts = overview.data?.accounts ?? []
  const current = useMemo(() => accounts.find((account) => account.id === selected) ?? null, [accounts, selected])
  const instruments = instrumentList.data?.items ?? []

  useEffect(() => {
    if (selected === null && accounts.length) setSelected(accounts[0].id)
  }, [accounts, selected])

  useEffect(() => {
    if (selected === null) {
      setSummary(null)
      setMovements([])
      return
    }
    let active = true
    setLoadingAccount(true)
    setError(null)
    Promise.all([realApi.summary(selected, undefined, true), realApi.movements(selected, 300)])
      .then(([nextSummary, nextMovements]) => {
        if (!active) return
        setSummary(nextSummary)
        setMovements(nextMovements.items)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : "No se pudo cargar la cuenta")
      })
      .finally(() => {
        if (active) setLoadingAccount(false)
      })
    return () => {
      active = false
    }
  }, [selected, version])

  const refresh = () => setVersion((value) => value + 1)

  const createAccount = async (event: React.FormEvent) => {
    event.preventDefault()
    setAccountBusy(true)
    setError(null)
    try {
      const created = await realApi.createAccount({
        ...accountForm,
        broker_name: accountForm.broker_name.trim(),
        broker_country: accountForm.broker_country.trim().toUpperCase(),
      })
      setSelected(created.id)
      setShowAccountForm(false)
      refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la cuenta")
    } finally {
      setAccountBusy(false)
    }
  }

  const deleteMovement = async (row: RealMovement) => {
    if (!selected) return
    if (!window.confirm(`¿Eliminar el movimiento #${row.id}? Se revisará el libro completo.`)) return
    try {
      await realApi.deleteMovement(selected, row.id)
      refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo eliminar el movimiento")
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Multimercado</p>
          <h1 className="mt-1 font-display text-4xl tracking-tight">Cartera real</h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-500">
            Registro y seguimiento de cuentas reales en distintas monedas y mercados. La plataforma no
            envía órdenes ni custodia credenciales de brókers.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {accounts.length ? (
            <select
              className="field max-w-[260px]"
              value={selected ?? ""}
              onChange={(event) => setSelected(Number(event.target.value))}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name} · {account.base_currency}
                </option>
              ))}
            </select>
          ) : null}
          <button type="button" className="btn-ghost text-xs" onClick={() => setShowAccountForm((open) => !open)}>
            {showAccountForm ? "Cerrar" : "Nueva cuenta"}
          </button>
          <Link to="/cartera" className="btn-ghost text-xs no-underline">
            Cartera simulada
          </Link>
        </div>
      </div>

      {error ? <ErrorNotice message={error} /> : null}
      {overview.error ? <ErrorNotice message={overview.error} onRetry={overview.reload} /> : null}

      {showAccountForm || accounts.length === 0 ? (
        <Card>
          <SectionHeader
            title={accounts.length ? "Nueva cuenta real" : "Crear la primera cuenta real"}
            subtitle="Cada cuenta tiene su propia moneda base, bróker, método contable y movimientos. Nunca se mezcla con la cartera simulada."
          />
          <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" onSubmit={createAccount}>
            <Field label="Nombre">
              <input
                className="field"
                value={accountForm.name}
                onChange={(event) => setAccountForm({ ...accountForm, name: event.target.value })}
                required
                maxLength={120}
              />
            </Field>
            <Field label="Bróker (texto, sin credenciales)">
              <input
                className="field"
                value={accountForm.broker_name}
                onChange={(event) => setAccountForm({ ...accountForm, broker_name: event.target.value })}
                maxLength={120}
              />
            </Field>
            <Field label="País del bróker" hint="Código ISO de dos letras.">
              <input
                className="field font-mono uppercase"
                value={accountForm.broker_country}
                onChange={(event) => setAccountForm({ ...accountForm, broker_country: event.target.value })}
                maxLength={2}
              />
            </Field>
            <Field label="Moneda base">
              <input
                className="field font-mono uppercase"
                value={accountForm.base_currency}
                onChange={(event) => setAccountForm({ ...accountForm, base_currency: event.target.value.toUpperCase() })}
                maxLength={3}
                required
              />
            </Field>
            <Field label="Método contable" hint="Se conserva el otro método para comparación interna.">
              <select
                className="field"
                value={accountForm.cost_method}
                onChange={(event) => setAccountForm({ ...accountForm, cost_method: event.target.value })}
              >
                <option value="fifo">FIFO</option>
                <option value="average">Coste medio</option>
              </select>
            </Field>
            <div className="flex items-end">
              <button type="submit" className="btn-primary w-full" disabled={accountBusy}>
                {accountBusy ? "Creando…" : "Crear cuenta"}
              </button>
            </div>
          </form>
        </Card>
      ) : null}

      {overview.data && overview.data.groups.length > 0 ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            {overview.data.groups.map((group) => (
              <Card key={group.currency}>
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                    Consolidado {group.currency}
                  </p>
                  <span className="text-[11px] text-ink-300">{group.accounts} cuenta(s)</span>
                </div>
                <p className="stat-value mt-2">
                  {group.total_value ? moneyString(group.total_value, group.currency) : "Sin valorar"}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-ink-500">
                  <span>Aportado: {moneyString(group.net_contributions, group.currency)}</span>
                  <span>Ganancia: {group.net_gain ? moneyString(group.net_gain, group.currency) : "—"}</span>
                  <span>XIRR: {group.xirr_pct ? pctRaw(group.xirr_pct) : "—"}</span>
                  <span>Dividendos: {moneyString(group.dividends, group.currency)}</span>
                </div>
                {!group.complete ? (
                  <p className="mt-2 text-[11px] text-amber-600">
                    Consolidado parcial: alguna posición no tiene cotización o tipo de cambio.
                  </p>
                ) : null}
              </Card>
            ))}
          </div>
          <p className="text-[11px] leading-relaxed text-ink-300">{overview.data.note}</p>
        </div>
      ) : null}

      {loadingAccount ? <p className="text-sm text-ink-500">Cargando cuenta…</p> : null}

      {current && summary ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-2xl">{summary.account.name}</h2>
              <p className="text-xs text-ink-300">
                {summary.account.broker_name || "Bróker sin especificar"} · moneda base{" "}
                {summary.base_currency} · {summary.account.cost_method === "fifo" ? "FIFO" : "coste medio"} ·{" "}
                {summary.movements} movimiento(s)
              </p>
            </div>
            <Tabs<Tab>
              tabs={[
                { id: "resumen", label: "Resumen" },
                { id: "movimientos", label: "Movimientos" },
                { id: "importar", label: "Importar" },
                { id: "documentos", label: "Documentos" },
              ]}
              value={tab}
              onChange={setTab}
            />
          </div>

          {tab === "resumen" ? (
            <RealSummaryView
              summary={summary}
              instruments={instruments}
              markets={markets.data ?? []}
              onChanged={refresh}
            />
          ) : null}

          {tab === "movimientos" ? (
            <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
              <Card>
                <SectionHeader
                  title="Historial"
                  subtitle="Orden cronológico del libro. Las cifras son las guardadas, no se recalculan con el cambio actual."
                />
                {movements.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-ink-900/15 p-5 text-sm text-ink-500">
                    Sin movimientos. Registra un depósito para empezar.
                  </p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th>Tipo</th>
                        <th>Instrumento</th>
                        <th className="text-right">Cantidad</th>
                        <th className="text-right">Precio / importe</th>
                        <th className="text-right">Costes</th>
                        <th>Origen</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {movements.map((row) => (
                        <tr key={row.id}>
                          <td className="whitespace-nowrap font-mono text-xs">{shortDate(row.movement_date)}</td>
                          <td className="text-xs">{TYPE_LABELS[row.movement_type] ?? row.movement_type}</td>
                          <td className="font-mono text-xs">{row.symbol ?? "—"}</td>
                          <td className="text-right font-mono text-xs">
                            {Number(row.quantity) ? Number(row.quantity).toLocaleString("es-ES") : "—"}
                          </td>
                          <td className="text-right font-mono text-xs">
                            {Number(row.price) ? `${row.price} ${row.currency}` : `${row.amount} ${row.currency}`}
                          </td>
                          <td className="text-right font-mono text-xs">
                            {Number(row.fee) ? `c ${row.fee}` : ""} {Number(row.tax) ? `i ${row.tax}` : ""}
                            {!Number(row.fee) && !Number(row.tax) ? "—" : ""}
                          </td>
                          <td>
                            <Badge tone={row.source === "manual" ? "muted" : "ai"}>{row.source}</Badge>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="text-[11px] font-semibold text-rust-600 underline"
                              onClick={() => deleteMovement(row)}
                            >
                              Eliminar
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
                <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
                  Al eliminar un movimiento se reproduce el libro completo: si una operación posterior
                  deja de ser válida, la eliminación se rechaza.
                </p>
              </Card>
              <Card>
                <SectionHeader title="Registrar movimiento" subtitle="Validación previa contra el libro completo." />
                <MovementForm
                  key={`movement-${current.id}`}
                  accountId={current.id}
                  baseCurrency={summary.base_currency}
                  instruments={instruments}
                  onCreated={refresh}
                />
              </Card>
            </div>
          ) : null}

          {tab === "importar" ? <ImportPanel accountId={current.id} onImported={refresh} /> : null}

          {tab === "documentos" ? (
            <DocumentsPanel
              accountId={current.id}
              baseCurrency={summary.base_currency}
              instruments={instruments}
              onConfirmed={refresh}
            />
          ) : null}
        </>
      ) : null}

      {!loadingAccount && !accounts.length && !overview.loading ? (
        <Notice tone="info">
          La cartera real está separada de la simulación. Crea una cuenta, registra depósitos y
          compras, y añade cotizaciones con fuente y fecha para valorarla.
        </Notice>
      ) : null}
    </div>
  )
}
