import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { systemApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Notice, Progress, SectionHeader, Skeleton, Stat } from "../components/ui"
import { money, relative, statusLabel } from "../lib/format"
import { useAuth } from "../lib/auth"

export function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [ticker, setTicker] = useState("")
  const { data, loading, error, reload } = useAsync(() => systemApi.dashboard(), [])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Panel</p>
          <h1 className="mt-1 font-display text-4xl tracking-tight text-ink-900">
            Hola, {user?.display_name || "analista"}.
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-500">
            Estado del sistema, investigaciones recientes y consumo de IA. Todo lo que ves aquí
            viene del backend: el navegador no calcula valoraciones.
          </p>
        </div>
        <form
          className="flex w-full max-w-sm gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            const value = ticker.trim().toUpperCase()
            if (value) navigate(`/empresas/${value}`)
          }}
        >
          <input
            className="field font-mono uppercase"
            placeholder="Ticker (AAPL)"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
            maxLength={12}
            aria-label="Ticker"
          />
          <button type="submit" className="btn-primary whitespace-nowrap">
            Analizar
          </button>
        </form>
      </div>

      {error ? <ErrorNotice message={error} onRetry={reload} /> : null}

      {loading || !data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton rows={2} />
            </Card>
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Motor financiero"
              value={data.system.engine_ready ? "Listo" : "Sin configurar"}
              tone={data.system.engine_ready ? "good" : "warn"}
              hint={
                data.system.engine_ready
                  ? "SEC EDGAR accesible con contacto configurado."
                  : "Falta NEXO_SEC_CONTACT en el entorno del servidor."
              }
            />
            <Stat
              label="IA"
              value={data.system.ai_available ? "Conectada" : "Modo básico"}
              tone={data.system.ai_available ? "good" : "warn"}
              hint={
                data.system.ai_available
                  ? `${data.system.providers.filter((p) => p.configured).length} proveedor(es) configurado(s).`
                  : "Sin claves: los informes se generan solo con el motor."
              }
            />
            <Stat
              label="Trabajos activos"
              value={data.system.jobs_running}
              hint="Investigaciones en cola o en ejecución."
            />
            <Stat
              label="Presupuesto IA"
              value={`${data.usage.used_usd.toFixed(2)} / ${data.usage.limit_usd.toFixed(2)} USD`}
              hint={`Periodo ${data.usage.period} · ${data.usage.jobs} trabajo(s)`}
            />
          </div>

          {data.alerts.length ? (
            <div className="space-y-2">
              {data.alerts.map((alert) => (
                <Notice
                  key={alert.message}
                  tone={alert.level === "error" ? "error" : alert.level === "warning" ? "warning" : "info"}
                >
                  {alert.message}
                </Notice>
              ))}
            </div>
          ) : null}

          <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
            <Card>
              <SectionHeader
                title="Investigaciones recientes"
                subtitle="Cada trabajo guarda su estado, coste y pasos de IA."
                action={
                  <Link to="/investigacion" className="btn-ghost text-xs no-underline">
                    Nueva
                  </Link>
                }
              />
              {data.jobs.length === 0 ? (
                <p className="rounded-lg border border-dashed border-ink-900/15 p-6 text-center text-sm text-ink-500">
                  Aún no hay investigaciones. Analiza una empresa y lanza la primera.
                </p>
              ) : (
                <ul className="divide-y divide-ink-900/5">
                  {data.jobs.map((job) => {
                    const status = statusLabel(job.status)
                    return (
                      <li key={job.id} className="flex items-center justify-between gap-3 py-3">
                        <div>
                          <Link
                            to={job.status === "completed" && job.report_id ? `/informes/${job.report_id}` : `/investigacion/${job.id}`}
                            className="font-mono text-sm font-medium text-ink-900 no-underline hover:text-moss-600"
                          >
                            {job.ticker}
                          </Link>
                          <p className="text-xs text-ink-300">
                            {job.stage} · {relative(job.created_at)} · perfil {job.profile}
                          </p>
                        </div>
                        <Badge tone={status.tone}>{status.text}</Badge>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>

            <div className="space-y-5">
              <Card>
                <SectionHeader title="Últimos informes" />
                {data.reports.length === 0 ? (
                  <p className="text-sm text-ink-500">Sin informes guardados.</p>
                ) : (
                  <ul className="divide-y divide-ink-900/5">
                    {data.reports.map((report) => (
                      <li key={report.id} className="flex items-center justify-between gap-2 py-2.5">
                        <Link
                          to={`/informes/${report.id}`}
                          className="truncate text-sm text-ink-800 no-underline hover:text-moss-600"
                        >
                          {report.title}
                        </Link>
                        <span className="shrink-0 text-[11px] uppercase tracking-wide text-ink-300">
                          {report.kind}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card>
                <SectionHeader title="Empresas observadas" />
                {data.companies.length === 0 ? (
                  <p className="text-sm text-ink-500">Todavía no has abierto ninguna empresa.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {data.companies.map((company) => (
                      <Link
                        key={company.ticker}
                        to={`/empresas/${company.ticker}`}
                        className="rounded-lg border border-ink-900/10 bg-white px-3 py-1.5 font-mono text-xs text-ink-700 no-underline hover:border-moss-600/40 hover:text-moss-600"
                      >
                        {company.ticker}
                      </Link>
                    ))}
                  </div>
                )}
              </Card>

              <Card>
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-ink-800">Consumo del mes</p>
                  <span className="font-mono text-xs text-ink-500">
                    {data.usage.tokens_in + data.usage.tokens_out} tokens
                  </span>
                </div>
                <div className="mt-3">
                  <Progress value={data.usage.limit_usd ? data.usage.used_usd / data.usage.limit_usd : 0} />
                </div>
                <p className="mt-2 text-xs text-ink-300">
                  Quedan {money(data.usage.remaining_usd)} de presupuesto. Si se agota, el modo
                  básico sin IA sigue disponible.
                </p>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
