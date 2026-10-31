import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { researchApi, type Job } from "../lib/api"
import { Badge, Card, ErrorNotice, Notice, Progress, SectionHeader } from "../components/ui"
import { dateTime, statusLabel } from "../lib/format"

const ROLE_LABELS: Record<string, string> = {
  business_researcher: "Investigador empresarial",
  financial_analyst: "Analista financiero",
  contrarian_analyst: "Analista contrario",
  evidence_auditor: "Auditor de evidencia",
  coordinator: "Analista coordinador",
}

const STAGES = ["en cola", "datos", "valoración", "agentes", "auditoría", "informe", "completado"]

export function ResearchDetail() {
  const { id = "" } = useParams()
  const jobId = Number(id)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let timer: number | undefined
    const load = async () => {
      try {
        const response = await researchApi.get(jobId)
        if (!active) return
        setJob(response)
        setError(null)
        if (response.status === "queued" || response.status === "running") {
          timer = window.setTimeout(load, 2000)
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "No se pudo cargar el trabajo")
      }
    }
    void load()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId])

  if (error) {
    return (
      <div className="space-y-3">
        <ErrorNotice message={error} />
        <Link to="/investigacion" className="btn-ghost text-sm no-underline">
          Volver
        </Link>
      </div>
    )
  }

  if (!job) {
    return <p className="text-sm text-ink-300">Cargando investigación…</p>
  }

  const status = statusLabel(job.status)
  const stageIndex = Math.max(
    0,
    STAGES.findIndex((stage) => stage === job.stage),
  )
  const progress =
    job.status === "completed" ? 1 : job.status === "failed" || job.status === "cancelled" ? stageIndex / STAGES.length : Math.max(0.05, stageIndex / STAGES.length)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs uppercase tracking-[0.14em] text-ink-300">Investigación #{job.id}</span>
            <Badge tone={status.tone}>{status.text}</Badge>
          </div>
          <h1 className="mt-2 font-display text-4xl tracking-tight">{job.ticker}</h1>
          <p className="mt-1 text-sm text-ink-500">
            Perfil {job.profile} · etapa «{job.stage}» · creada {dateTime(job.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/investigacion" className="btn-ghost text-xs no-underline">
            Historial
          </Link>
          {job.status === "running" || job.status === "queued" ? (
            <button
              type="button"
              className="btn-danger text-xs"
              onClick={async () => {
                await researchApi.cancel(job.id)
                setJob({ ...job, stage: "cancelación solicitada" })
              }}
            >
              Cancelar
            </button>
          ) : null}
          {job.report_id ? (
            <Link to={`/informes/${job.report_id}`} className="btn-primary text-xs no-underline">
              Abrir informe
            </Link>
          ) : null}
        </div>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ink-600">
            {job.status === "queued"
              ? "En cola: el ejecutor la tomará en cuanto haya un hueco."
              : job.status === "running"
                ? "Ejecutándose en el servidor. Puedes cerrar la pestaña y volver."
                : job.status === "completed"
                  ? "Completada. El informe está guardado en tu historial."
                  : job.status === "cancelled"
                    ? "Cancelada. Si ya había pasos completados, el informe parcial se conserva."
                    : "Fallida."}
          </p>
          <div className="flex gap-3 font-mono text-xs text-ink-500">
            <span>{job.tokens_in + job.tokens_out} tokens</span>
            <span>{job.cost_usd.toFixed(4)} / {job.budget_usd.toFixed(2)} USD</span>
            <span>intento {job.attempts}</span>
          </div>
        </div>
        <div className="mt-3">
          <Progress value={progress} />
        </div>
        {job.error ? (
          <div className="mt-3">
            <Notice tone="error">{job.error}</Notice>
          </div>
        ) : null}
      </Card>

      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <SectionHeader title="Pasos de IA" subtitle="Cada rol, su modelo y su consumo real." />
          {job.steps.length === 0 ? (
            <p className="text-sm text-ink-500">
              Sin pasos de IA todavía. El perfil básico no ejecuta modelos: el informe se construye
              con el motor y la procedencia.
            </p>
          ) : (
            <ol className="space-y-4">
              {job.steps.map((step, index) => (
                <li key={`${step.role}-${index}`} className="relative border-l border-ink-900/10 pl-4">
                  <span className="absolute -left-[5px] top-1.5 h-2 w-2 rounded-full bg-moss-500" />
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-ink-800">
                      {ROLE_LABELS[step.role] ?? step.role}
                    </p>
                    <Badge tone={step.status === "completed" ? "fact" : step.status === "failed" ? "warn" : "muted"}>
                      {step.status}
                    </Badge>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-ink-300">
                    {step.provider}:{step.model} · {step.tokens_in}/{step.tokens_out} tokens ·{" "}
                    {step.cost_usd.toFixed(4)} USD
                  </p>
                  {step.error ? <p className="mt-1 text-xs text-rust-600">{step.error}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card>
          <SectionHeader title="Qué se guarda" />
          <ul className="space-y-2 text-sm leading-relaxed text-ink-500">
            <li>El estado del trabajo en la base de datos, no en memoria: un reinicio no lo pierde.</li>
            <li>Los pasos completados, con modelo, tokens y coste.</li>
            <li>El informe con sus 18 secciones y el resultado de la auditoría de cifras.</li>
            <li>El consumo acumulado del mes, para no exceder el presupuesto.</li>
          </ul>
          <p className="mt-4 text-xs leading-relaxed text-ink-300">
            Si el trabajo se agota por presupuesto o tiempo, se detiene y conserva lo que ya se
            había producido. No se reintenta indefinidamente.
          </p>
        </Card>
      </div>
    </div>
  )
}
