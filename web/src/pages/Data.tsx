import { useEffect, useState } from "react"
import {
  dataApi,
  marketsApi,
  type DataRun,
  type FundamentalFact,
  type Instrument,
} from "../lib/api"
import { useAsync } from "../lib/useAsync"
import {
  Badge,
  Card,
  ErrorNotice,
  Field,
  Notice,
  SectionHeader,
  Spinner,
  Stat,
  Table,
} from "../components/ui"
import { dateTime, qualityLabel, shortDate } from "../lib/format"

type Tone = "fact" | "ai" | "warn" | "muted"

const RUN_STATE: Record<string, { text: string; tone: Tone }> = {
  queued: { text: "En cola", tone: "muted" },
  running: { text: "En ejecución", tone: "ai" },
  success: { text: "Correcta", tone: "fact" },
  partial: { text: "Parcial", tone: "warn" },
  cached: { text: "Caché", tone: "muted" },
  skipped: { text: "Sin cambios", tone: "muted" },
  failed: { text: "Fallida", tone: "warn" },
}

const FX_KIND: Record<string, string> = {
  official: "oficial",
  market: "mercado",
  reference: "referencia",
  estimated: "estimado",
}

const CATEGORY: Record<string, string> = {
  fx: "divisas",
  prices: "precios",
  fundamentals: "fundamentales",
  news: "noticias",
}

function runState(status: string) {
  return RUN_STATE[status] ?? { text: status, tone: "muted" as Tone }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function Data() {
  const { data, loading, error, reload } = useAsync(() => dataApi.status(), [])
  const news = useAsync(() => dataApi.news(), [])
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pollsLeft, setPollsLeft] = useState(0)
  const [searchTerm, setSearchTerm] = useState("")
  const [results, setResults] = useState<Instrument[]>([])
  const [selected, setSelected] = useState<Instrument | null>(null)
  const [facts, setFacts] = useState<{ items: FundamentalFact[]; note: string } | null>(null)
  const [busyInstrument, setBusyInstrument] = useState(false)

  // Tras una sincronización en segundo plano se refresca el estado unas veces.
  useEffect(() => {
    if (pollsLeft <= 0) return
    const timer = setTimeout(() => {
      reload()
      setPollsLeft((value) => value - 1)
    }, 1500)
    return () => clearTimeout(timer)
  }, [pollsLeft, reload])

  const track = (message: string) => {
    setNotice(message)
    setActionError(null)
    setPollsLeft(8)
    reload()
  }

  const syncFx = async () => {
    setNotice(null)
    setActionError(null)
    try {
      const result = await dataApi.syncFx("USD", ["EUR", "BOB"])
      track(
        result.status === "queued"
          ? "Divisas encoladas: el resultado aparece en Ejecuciones."
          : `Divisas: ${result.status}.`,
      )
    } catch (err) {
      setActionError(errorMessage(err, "No se pudo encolar la sincronización de divisas."))
    }
  }

  const search = async (event: React.FormEvent) => {
    event.preventDefault()
    setActionError(null)
    try {
      const response = await marketsApi.instruments(searchTerm)
      setResults(response.items)
    } catch (err) {
      setActionError(errorMessage(err, "No se pudo buscar el instrumento."))
    }
  }

  const pick = async (instrument: Instrument) => {
    setSelected(instrument)
    setFacts(null)
    setActionError(null)
    if (instrument.cik != null) {
      try {
        const response = await dataApi.fundamentals(instrument.uid)
        setFacts({ items: response.items, note: response.note })
      } catch {
        setFacts(null)
      }
    }
  }

  const syncSelected = async (kind: "prices" | "fundamentals") => {
    if (!selected) return
    setBusyInstrument(true)
    setNotice(null)
    setActionError(null)
    try {
      if (kind === "prices") await dataApi.syncPrices(selected.uid)
      else await dataApi.syncFundamentals(selected.uid)
      track(`${selected.symbol}: sincronización de ${kind === "prices" ? "precios" : "fundamentales"} encolada.`)
      if (kind === "fundamentals") {
        try {
          const response = await dataApi.fundamentals(selected.uid)
          setFacts({ items: response.items, note: response.note })
        } catch {
          /* la lista se actualizará en la siguiente carga */
        }
      }
    } catch (err) {
      setActionError(errorMessage(err, "No se pudo encolar la sincronización."))
    } finally {
      setBusyInstrument(false)
    }
  }

  const toggleAuto = async (uid: string, enabled: boolean) => {
    setActionError(null)
    try {
      await dataApi.toggleAutoSync(uid, enabled)
      setNotice(
        enabled
          ? "Actualización automática activada para el instrumento."
          : "Actualización automática desactivada.",
      )
      reload()
    } catch (err) {
      setActionError(errorMessage(err, "No se pudo cambiar la actualización automática."))
    }
  }

  const activeRuns = (data?.runs ?? []).filter(
    (run) => run.status === "queued" || run.status === "running",
  )
  const providers = data?.providers ?? []
  const connected = providers.filter((provider) => provider.configured).length
  const stalePairs = (data?.fx ?? []).filter((pair) => pair.available && pair.stale).length
  const stalePrices = (data?.prices ?? []).filter((price) => price.stale).length

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">
          Multimercado
        </p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Datos de mercado</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Divisas, precios históricos y fundamentales recopilados por proveedores reales. Cada dato
          guarda su fuente, la fecha del dato y la fecha de consulta: los cierres diarios nunca se
          presentan como tiempo real.
        </p>
      </div>

      {error ? <ErrorNotice message={error} onRetry={reload} /> : null}
      {actionError ? <ErrorNotice message={actionError} /> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}
      {pollsLeft > 0 && activeRuns.length ? (
        <Notice tone="info">
          Actualización en curso ({activeRuns.length} ejecución(es) activas). Esta pantalla se
          actualiza sola.
        </Notice>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Proveedores conectados"
          value={`${connected}/${providers.length}`}
          hint="Los sin conexión aparecen declarados, nunca como activos."
        />
        <Stat
          label="Pares de divisas con datos"
          value={`${(data?.fx ?? []).filter((pair) => pair.available).length}/${(data?.fx ?? []).length}`}
          hint="Fecha real del último dato por par."
          tone={stalePairs ? "warn" : "good"}
        />
        <Stat
          label="Precios obsoletos"
          value={String(stalePrices)}
          hint="Cierres más antiguos que el umbral configurado."
          tone={stalePrices ? "warn" : "good"}
        />
        <Stat
          label="Última ejecución"
          value={data?.runs?.[0] ? runState(data.runs[0].status).text : "—"}
          hint={
            data?.runs?.[0]
              ? `${data.runs[0].provider} · ${dateTime(data.runs[0].finished_at ?? data.runs[0].started_at)}`
              : "Todavía no se ha ejecutado ninguna recopilación."
          }
          tone={data?.runs?.[0] && runState(data.runs[0].status).tone === "warn" ? "warn" : "default"}
        />
      </div>

      <Card>
        <SectionHeader
          title="Sincronizar divisas"
          subtitle="Consulta la tasa de cierre de USD frente a EUR y BOB desde los proveedores configurados. La respuesta se encola en segundo plan y no bloquea esta pantalla."
          action={
            <button type="button" className="btn-primary text-sm" onClick={syncFx}>
              Sincronizar USD → EUR, BOB
            </button>
          }
        />
        <p className="text-xs leading-relaxed text-ink-500">
          La primera fuente es Frankfurter (bancos centrales, incluido el BCBO); ExchangeRate-API
          sirve como segunda opinión y sus divergencias se registran como anomalía sin unificar las
          tasas. Las respuestas se cachean para no repetir peticiones dentro del plazo diario.
        </p>
      </Card>

      <Card>
        <SectionHeader
          title="Proveedores"
          subtitle="Catálogo con licencia, límites y estado de conexión real."
        />
        {loading && !data ? (
          <Spinner label="Cargando estado…" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Proveedor</th>
                <th>Categoría</th>
                <th>Estado</th>
                <th>Historial</th>
                <th>Límites y condiciones</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.name}>
                  <td>
                    <p className="text-sm font-medium text-ink-900">{provider.label}</p>
                    {provider.website ? (
                      <a
                        href={provider.website}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-[11px] text-moss-600 no-underline hover:underline"
                      >
                        {provider.website.replace(/^https?:\/\//, "")}
                      </a>
                    ) : null}
                  </td>
                  <td className="text-xs text-ink-500">
                    {CATEGORY[provider.category] ?? provider.category}
                  </td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      <Badge tone={provider.configured ? "fact" : "warn"}>
                        {provider.configured ? "conectado" : "sin conexión"}
                      </Badge>
                      {provider.selected ? <Badge tone="ai">seleccionado</Badge> : null}
                    </div>
                  </td>
                  <td className="text-xs text-ink-500">
                    {provider.supports_history ? "sí" : "solo tasa actual"}
                  </td>
                  <td className="max-w-[22rem] text-xs leading-relaxed text-ink-500">
                    {provider.limits}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <SectionHeader
          title="Divisas"
          subtitle="Último dato disponible por par, con todas las fuentes que lo aportaron."
        />
        {loading && !data ? (
          <Spinner />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Par</th>
                <th>Fecha del dato</th>
                <th>Valores por fuente</th>
                <th className="text-right">Estado</th>
              </tr>
            </thead>
            <tbody>
              {(data?.fx ?? []).map((pair) => (
                <tr key={pair.pair}>
                  <td className="font-mono text-sm font-medium text-ink-900">{pair.pair}</td>
                  <td className="text-xs text-ink-500">
                    {pair.available ? (
                      <>
                        {shortDate(pair.as_of)}
                        <span className="ml-2 text-ink-300">{pair.days_old} d</span>
                      </>
                    ) : (
                      <span className="text-ink-300">sin datos</span>
                    )}
                  </td>
                  <td className="text-xs">
                    {pair.available ? (
                      <div className="space-y-1">
                        {(pair.values ?? []).map((value) => (
                          <p key={value.source} className="font-mono">
                            {value.rate}
                            <span className="ml-2 text-ink-300">
                              {value.source} · {FX_KIND[value.kind] ?? value.kind} ·{" "}
                              {qualityLabel(value.quality).text}
                            </span>
                          </p>
                        ))}
                      </div>
                    ) : (
                      <span className="text-ink-300">{pair.reason}</span>
                    )}
                  </td>
                  <td className="text-right">
                    {!pair.available ? (
                      <Badge tone="warn">sin datos</Badge>
                    ) : pair.stale ? (
                      <Badge tone="warn">desactualizado</Badge>
                    ) : (
                      <Badge tone="fact">actual</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
          Los tipos se guardan por fecha de calendario del dato. Una tasa oficial de banco central y
          una tasa de mercado conviven con su etiqueta: no se fusionan.
        </p>
      </Card>

      <Card>
        <SectionHeader
          title="Precios guardados"
          subtitle="Cierres diarios por instrumento, con su frescura y su procedencia."
        />
        {loading && !data ? (
          <Spinner />
        ) : (data?.prices.length ?? 0) === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-900/15 p-5 text-sm text-ink-500">
            Todavía no hay precios de proveedor. Sincroniza un instrumento desde el bloque inferior
            o activa su actualización automática.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Instrumento</th>
                <th>Último cierre</th>
                <th>Fuente</th>
                <th>Calidad</th>
                <th className="text-right">Estado</th>
                <th className="text-right">Auto</th>
              </tr>
            </thead>
            <tbody>
              {(data?.prices ?? []).map((row) => (
                <tr key={row.instrument_uid}>
                  <td>
                    <p className="font-mono text-sm font-medium text-ink-900">{row.symbol}</p>
                    <p className="text-[11px] text-ink-300">{row.name}</p>
                  </td>
                  <td className="text-xs text-ink-500">
                    {shortDate(row.as_of)}
                    <span className="ml-2 text-ink-300">{row.age_days} d</span>
                  </td>
                  <td className="font-mono text-xs text-ink-500">{row.source}</td>
                  <td>
                    <Badge tone={qualityLabel(row.quality).tone}>
                      {qualityLabel(row.quality).text}
                    </Badge>
                  </td>
                  <td className="text-right">
                    {row.stale ? <Badge tone="warn">desactualizado</Badge> : <Badge tone="fact">actual</Badge>}
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      className="rounded border border-ink-900/10 px-2 py-0.5 text-[11px] text-ink-500 hover:border-moss-600/40 hover:text-moss-600"
                      onClick={() => toggleAuto(row.instrument_uid, !row.auto_sync)}
                    >
                      {row.auto_sync ? "desactivar" : "activar"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <SectionHeader
          title="Actualizar un instrumento"
          subtitle="Busca por símbolo, nombre o ISIN y lanza la recopilación de precios o fundamentales en segundo plan."
        />
        <form onSubmit={search} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1">
            <Field label="Buscar instrumento" hint="Ej.: AAPL, SAP, SAN.">
              <input
                className="field"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="AAPL"
                maxLength={80}
              />
            </Field>
          </div>
          <button type="submit" className="btn-ghost text-sm">
            Buscar
          </button>
        </form>

        {results.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {results.map((instrument) => (
              <button
                key={instrument.uid}
                type="button"
                onClick={() => pick(instrument)}
                className={`rounded-md border px-3 py-1.5 text-xs transition-colors ${
                  selected?.uid === instrument.uid
                    ? "border-moss-600/50 bg-moss-100 text-moss-700"
                    : "border-ink-900/10 bg-white/70 text-ink-600 hover:border-moss-600/40"
                }`}
              >
                <span className="font-mono font-medium">{instrument.symbol}</span>
                <span className="ml-2 text-ink-300">{instrument.market}</span>
              </button>
            ))}
          </div>
        ) : null}

        {selected ? (
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-medium text-ink-900">{selected.symbol}</span>
              <span className="text-xs text-ink-500">{selected.name}</span>
              <Badge tone="muted">{selected.currency}</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary text-sm"
                disabled={busyInstrument}
                onClick={() => syncSelected("prices")}
              >
                Sincronizar precios
              </button>
              <button
                type="button"
                className="btn-ghost text-sm"
                disabled={busyInstrument || selected.cik == null}
                onClick={() => syncSelected("fundamentals")}
              >
                Sincronizar fundamentales
              </button>
              <button
                type="button"
                className="btn-ghost text-sm"
                onClick={() => toggleAuto(selected.uid, true)}
              >
                Activar auto-actualización
              </button>
            </div>
            {selected.cik == null ? (
              <Notice tone="info">
                Este instrumento no tiene CIK: los fundamentales solo existen para emisores con
                EDGAR (EE. UU.). No se sustituye por otra fuente ni se calcula nada en su lugar.
              </Notice>
            ) : null}
            {facts ? (
              facts.items.length === 0 ? (
                <p className="text-sm text-ink-500">
                  Sin fundamentales guardados todavía. Ejecuta la sincronización.
                </p>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <th>Periodo</th>
                      <th className="text-right">Ingresos</th>
                      <th className="text-right">Beneficio neto</th>
                      <th className="text-right">EPS diluido</th>
                      <th className="text-right">Efectivo</th>
                      <th className="text-right">Deuda LP</th>
                      <th>Fuente</th>
                    </tr>
                  </thead>
                  <tbody>
                    {facts.items.map((fact) => (
                      <tr key={`${fact.period_type}-${fact.fiscal_end}`}>
                        <td className="text-xs">
                          {fact.period_type === "annual" ? "anual" : "trimestral"} ·{" "}
                          {shortDate(fact.fiscal_end)}
                        </td>
                        <td className="text-right font-mono text-xs">{fact.revenue ?? "—"}</td>
                        <td className="text-right font-mono text-xs">{fact.net_income ?? "—"}</td>
                        <td className="text-right font-mono text-xs">{fact.eps_diluted ?? "—"}</td>
                        <td className="text-right font-mono text-xs">{fact.cash ?? "—"}</td>
                        <td className="text-right font-mono text-xs">{fact.total_debt ?? "—"}</td>
                        <td>
                          <Badge tone="muted">{fact.quality}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )
            ) : null}
            {facts ? <p className="text-[11px] leading-relaxed text-ink-300">{facts.note}</p> : null}
          </div>
        ) : null}
      </Card>

      <Card>
        <SectionHeader
          title="Ejecuciones"
          subtitle="Cada recopilación deja peticiones realizadas, registros guardados y sus anomalías."
          action={
            <button type="button" className="btn-ghost text-xs" onClick={reload}>
              Actualizar
            </button>
          }
        />
        {loading && !data ? (
          <Spinner />
        ) : (data?.runs.length ?? 0) === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-900/15 p-5 text-sm text-ink-500">
            Sin ejecuciones todavía. Lanza una sincronización desde los bloques superiores.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Proveedor</th>
                <th>Estado</th>
                <th className="text-right">Datos</th>
                <th className="text-right">Peticiones</th>
                <th>Finalizada</th>
                <th>Error / anomalías</th>
              </tr>
            </thead>
            <tbody>
              {(data?.runs ?? []).slice(0, 15).map((run: DataRun) => {
                const anomalies = Array.isArray(run.details?.anomalies)
                  ? (run.details.anomalies as unknown[]).length
                  : 0
                return (
                  <tr key={run.id}>
                    <td>
                      <p className="text-sm font-medium text-ink-900">{run.provider}</p>
                      <p className="text-[11px] text-ink-300">
                        {CATEGORY[run.category] ?? run.category} · #{run.id}
                      </p>
                    </td>
                    <td>
                      <Badge tone={runState(run.status).tone}>{runState(run.status).text}</Badge>
                    </td>
                    <td className="text-right font-mono text-xs">
                      {run.items_stored}/{run.items_fetched}
                      {run.items_skipped ? <span className="text-ink-300"> · {run.items_skipped}↓</span> : null}
                    </td>
                    <td className="text-right font-mono text-xs">{run.request_count}</td>
                    <td className="text-xs text-ink-500">{dateTime(run.finished_at)}</td>
                    <td className="max-w-[20rem] text-xs">
                      {run.error ? (
                        <span className="text-rust-600">{run.error}</span>
                      ) : anomalies ? (
                        <span className="text-amber-600">{anomalies} anomalía(s) registrada(s)</span>
                      ) : (
                        <span className="text-ink-300">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Automatización" subtitle="Planificador de recopilaciones." />
          {data ? (
            <div className="space-y-3 text-sm text-ink-600">
              <p>
                Estado:{" "}
                <Badge tone={data.scheduler.enabled ? "fact" : "muted"}>
                  {data.scheduler.enabled ? "activo" : "apagado"}
                </Badge>
                {data.scheduler.enabled
                  ? ` cada ${data.scheduler.interval_minutes} min`
                  : " por defecto: no hay tráfico externo sin consentimiento"}
              </p>
              <p className="text-xs text-ink-500">
                Pares programados: {data.scheduler.pairs.join(" · ") || "—"}
              </p>
              <p className="text-[11px] leading-relaxed text-ink-300">
                Se activa con <code>NEXO_DATA_SYNC_INTERVAL_MINUTES</code> y los pares se ajustan con{" "}
                <code>NEXO_DATA_SYNC_PAIRS</code>. Las ejecuciones interrumpidas se recuperan al
                arrancar y no se duplican peticiones con la misma clave.
              </p>
            </div>
          ) : (
            <Spinner />
          )}
        </Card>

        <Card>
          <SectionHeader title="Noticias y eventos" subtitle="Sección honesta: sin fuente no hay contenido." />
          {news.data ? (
            <Notice tone={news.data.available ? "success" : "warning"}>{news.data.reason}</Notice>
          ) : news.error ? (
            <ErrorNotice message={news.error} onRetry={news.reload} />
          ) : (
            <Spinner label="Consultando…" />
          )}
        </Card>
      </div>
    </div>
  )
}
