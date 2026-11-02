import { useState } from "react"
import { boardApi, marketsApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, EmptyState, ErrorNotice, Field, Notice, SectionHeader, Spinner, Tabs, Table } from "../components/ui"

type Horizon = "" | "short" | "medium" | "long"

const HORIZON_LABEL: Record<string, string> = { short: "corto", medium: "medio", long: "largo" }

export function Watchlist() {
  const list = useAsync(() => boardApi.watchlist(), [])
  const [query, setQuery] = useState("")
  const [found, setFound] = useState<Awaited<ReturnType<typeof marketsApi.instruments>> | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const search = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      setFound(await marketsApi.instruments(query.trim(), ""))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "La búsqueda falló")
    } finally {
      setBusy(false)
    }
  }

  const follow = async (uid: string) => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await boardApi.addWatchlist(uid)
      setMessage(result.already ? "Ya lo seguías." : "Instrumento añadido al seguimiento.")
      list.reload()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo añadir")
    } finally {
      setBusy(false)
    }
  }

  const unfollow = async (uid: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await boardApi.removeWatchlist(uid)
      setMessage("Dejado de seguir.")
      list.reload()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo quitar")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Tablero</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Seguimiento</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Tu watchlist privada y los estudios de oportunidad: señales deterministas sobre datos con
          procedencia, nunca invitaciones a comprar.
        </p>
      </div>

      {list.error ? <ErrorNotice message={list.error} onRetry={list.reload} /> : null}
      {message ? <Notice tone="success">{message}</Notice> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <div className="space-y-5">
          <Card>
            <SectionHeader title="Watchlist" subtitle={`${list.data?.items.length ?? 0} instrumentos`} />
            {list.loading && !list.data ? (
              <Spinner />
            ) : (list.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                title="Aún no sigues nada"
                description="Busca un instrumento por símbolo y añádelo para tenerlo a la vista."
              />
            ) : (
              <ul className="divide-y divide-ink-900/10">
                {(list.data?.items ?? []).map((item) => (
                  <li key={item.instrument_uid} className="flex items-center justify-between gap-3 py-3">
                    <div>
                      <p className="font-mono text-sm font-semibold text-ink-900">{item.symbol}</p>
                      <p className="text-xs text-ink-500">{item.name}</p>
                      {item.note ? <p className="mt-1 text-xs text-ink-300">{item.note}</p> : null}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-ink-300">{item.currency}</span>
                      <button
                        type="button"
                        className="text-xs font-semibold text-rust-600 underline"
                        disabled={busy}
                        onClick={() => unfollow(item.instrument_uid)}
                      >
                        Quitar
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <SectionHeader title="Añadir instrumento" />
            <form className="flex items-end gap-3" onSubmit={search}>
              <Field label="Símbolo o nombre">
                <input
                  className="field"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="AAPL, VOD…"
                />
              </Field>
              <button type="submit" className="btn-primary" disabled={busy || !query.trim()}>
                Buscar
              </button>
            </form>
            {found ? (
              <ul className="mt-4 divide-y divide-ink-900/10">
                {found.items.slice(0, 8).map((item) => (
                  <li key={item.uid} className="flex items-center justify-between gap-3 py-2">
                    <div>
                      <p className="font-mono text-sm font-semibold">{item.symbol}</p>
                      <p className="text-xs text-ink-500">
                        {item.name} · {item.market_name} · {item.currency}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => follow(item.uid)}
                    >
                      Seguir
                    </button>
                  </li>
                ))}
                {found.items.length === 0 ? (
                  <li className="py-3 text-sm text-ink-500">Sin resultados para esa búsqueda.</li>
                ) : null}
              </ul>
            ) : null}
          </Card>
        </div>

        <OpportunitiesPanel />
      </div>
    </div>
  )
}

function OpportunitiesPanel() {
  const [horizon, setHorizon] = useState<Horizon>("")
  const study = useAsync(() => boardApi.opportunities(horizon || undefined), [horizon])

  return (
    <Card>
      <SectionHeader
        title="Oportunidades"
        subtitle="Estudio cuantitativo (no recomendación): puntuación de señales sobre datos presentes."
        action={
          <Tabs<Horizon>
            tabs={[
              { id: "", label: "Todas" },
              { id: "short", label: "Corto" },
              { id: "medium", label: "Medio" },
              { id: "long", label: "Largo" },
            ]}
            value={horizon}
            onChange={setHorizon}
          />
        }
      />
      <Notice>{study.data?.note ?? "Calculando el estudio…"}</Notice>
      {study.error ? (
        <div className="mt-4">
          <ErrorNotice message={study.error} onRetry={study.reload} />
        </div>
      ) : null}
      {study.loading && !study.data ? (
        <div className="mt-4">
          <Spinner />
        </div>
      ) : study.data && study.data.items.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            title="Sin resultados con los datos actuales"
            description="Ningún instrumento tiene cierres y fundamentales suficientes para puntuar. La plataforma no fuerza conclusiones sin datos."
          />
        </div>
      ) : study.data ? (
        <div className="mt-4 space-y-5">
          <Table>
            <thead>
              <tr>
                <th>Instrumento</th>
                <th>Puntuación</th>
                <th>Horizonte</th>
                <th>Señales</th>
                <th>Período</th>
              </tr>
            </thead>
            <tbody>
              {study.data.items.map((item) => (
                <tr key={item.instrument.uid}>
                  <td>
                    <span className="font-mono text-xs font-semibold">{item.instrument.symbol}</span>
                    <span className="ml-2 text-xs text-ink-500">{item.instrument.name}</span>
                  </td>
                  <td className="font-mono text-sm font-semibold">{item.score}/100</td>
                  <td>
                    <Badge tone="muted">{HORIZON_LABEL[item.horizon] ?? item.horizon}</Badge>
                  </td>
                  <td className="text-xs text-ink-500">
                    {Object.entries(item.signals)
                      .slice(0, 4)
                      .map(([key, value]) => `${key}: ${String(value)}`)
                      .join(" · ")}
                  </td>
                  <td className="font-mono text-xs">{item.fiscal_period}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          {study.data.skipped.length > 0 ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
                Descartados ({study.data.counts.skipped})
              </p>
              <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                {study.data.skipped.slice(0, 12).map((row, index) => (
                  <li key={`${row.symbol}-${index}`} className="text-xs text-ink-500">
                    <span className="font-mono font-semibold">{row.symbol}</span>: {row.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
