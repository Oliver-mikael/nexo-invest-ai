import { Link } from "react-router-dom"
import { dataApi, researchApi, systemApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, EmptyState, ErrorNotice, SectionHeader, Spinner, Table } from "../components/ui"

const JOB_STATUS_TONE: Record<string, "fact" | "ai" | "warn" | "muted"> = {
  queued: "muted",
  running: "ai",
  completed: "fact",
  failed: "warn",
  cancelled: "muted",
  success: "fact",
  partial: "warn",
  cached: "muted",
  skipped: "muted",
}

const JOB_STATUS_LABEL: Record<string, string> = {
  queued: "en cola",
  running: "en curso",
  completed: "completada",
  failed: "fallida",
  cancelled: "cancelada",
  success: "correcta",
  partial: "parcial",
  cached: "caché",
  skipped: "omitida",
}

/**
 * Tareas del sistema: investigaciones con IA, ejecuciones de datos y estado
 * del worker/planificador. Todo vive en el servidor: cerrar la app no detiene
 * nada de lo que está en cola.
 */
export function Jobs() {
  const dashboard = useAsync(() => systemApi.dashboard(), [])
  const research = useAsync(() => researchApi.list(), [])
  const runs = useAsync(() => dataApi.runs(20), [])
  const status = useAsync(() => dataApi.status(), [])

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Operación</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Tareas</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Cola persistente del servidor: investigaciones, sincronizaciones de datos y planificador.
          Las tareas siguen aunque cierres la aplicación.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
            Investigaciones en curso
          </p>
          <p className="stat-value mt-2">{dashboard.data?.system.jobs_running ?? "—"}</p>
        </Card>
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
            Proveedor de IA
          </p>
          <p className="stat-value mt-2">{dashboard.data?.system.ai_available ? "disponible" : "no disponible"}</p>
        </Card>
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
            Planificador de datos
          </p>
          <p className="stat-value mt-2">
            {status.data?.scheduler.enabled ? "activo" : "manual"}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            {status.data ? `intervalo ${status.data.scheduler.interval_minutes} min` : "…"}
          </p>
        </Card>
      </div>

      {dashboard.error ? <ErrorNotice message={dashboard.error} onRetry={dashboard.reload} /> : null}

      <Card>
        <SectionHeader
          title="Investigaciones"
          subtitle="Jobs de la orquestación multiagente, con presupuesto y pasos."
          action={
            <Link to="/investigacion" className="btn-ghost text-xs no-underline">
              Ir a investigación
            </Link>
          }
        />
        {research.error ? <ErrorNotice message={research.error} onRetry={research.reload} /> : null}
        {research.loading && !research.data ? (
          <Spinner />
        ) : (research.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="Sin investigaciones"
            description="Lanza una investigación desde la pantalla de investigación para ver aquí su progreso."
          />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>#</th>
                <th>Empresa</th>
                <th>Estado</th>
                <th>Etapa</th>
                <th>Perfil</th>
                <th>Coste</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(research.data?.items ?? []).map((job) => (
                <tr key={job.id}>
                  <td className="font-mono text-xs">{job.id}</td>
                  <td className="font-mono text-xs font-semibold">{job.ticker}</td>
                  <td>
                    <Badge tone={JOB_STATUS_TONE[job.status] ?? "muted"}>
                      {JOB_STATUS_LABEL[job.status] ?? job.status}
                    </Badge>
                  </td>
                  <td className="text-xs text-ink-500">{job.stage || "—"}</td>
                  <td className="text-xs">{job.profile}</td>
                  <td className="font-mono text-xs">${job.cost_usd.toFixed(4)}</td>
                  <td className="text-right">
                    {job.report_id ? (
                      <Link to={`/informes/${job.report_id}`} className="text-xs font-semibold underline">
                        Informe
                      </Link>
                    ) : (
                      <Link to={`/investigacion/${job.id}`} className="text-xs font-semibold underline">
                        Ver
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <SectionHeader
          title="Ejecuciones de datos"
          subtitle="Sincronizaciones de divisas, precios y fundamentales con reintentos y anti-duplicados."
          action={
            <Link to="/datos" className="btn-ghost text-xs no-underline">
              Ir a datos
            </Link>
          }
        />
        {runs.error ? <ErrorNotice message={runs.error} onRetry={runs.reload} /> : null}
        {runs.loading && !runs.data ? (
          <Spinner />
        ) : (runs.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="Sin ejecuciones"
            description="Cuando actives una sincronización aparecerá aquí con sus reintentos y resultados."
          />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>#</th>
                <th>Proveedor</th>
                <th>Tarea</th>
                <th>Estado</th>
                <th>Intentos</th>
                <th>Almacenados</th>
                <th>Inicio</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data?.items ?? []).map((run) => (
                <tr key={run.id}>
                  <td className="font-mono text-xs">{run.id}</td>
                  <td className="text-xs">{run.provider}</td>
                  <td className="font-mono text-[11px] text-ink-500">{run.task_key}</td>
                  <td>
                    <Badge tone={JOB_STATUS_TONE[run.status] ?? "muted"}>
                      {JOB_STATUS_LABEL[run.status] ?? run.status}
                    </Badge>
                  </td>
                  <td className="font-mono text-xs">{run.attempts}</td>
                  <td className="font-mono text-xs">{run.items_stored}</td>
                  <td className="font-mono text-[11px] text-ink-500">
                    {run.started_at ? new Date(run.started_at).toLocaleString("es") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {runs.data && runs.data.items.some((run) => run.error) ? (
          <div className="mt-3 space-y-2">
            {runs.data.items
              .filter((run) => run.error)
              .slice(0, 3)
              .map((run) => (
                <p key={run.id} className="text-xs text-rust-600">
                  #{run.id}: {run.error}
                </p>
              ))}
          </div>
        ) : null}
      </Card>
    </div>
  )
}
