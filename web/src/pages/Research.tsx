import { useEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ApiError, researchApi, type Job } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Field, Notice, SectionHeader, Table } from "../components/ui"
import { relative, statusLabel } from "../lib/format"

const PROFILES = [
  {
    id: "basic",
    title: "Básico",
    body: "Sin IA. Informe con el motor y la procedencia; las secciones cualitativas se declaran no disponibles.",
    cost: "0 USD",
  },
  {
    id: "standard",
    title: "Estándar",
    body: "Cinco roles con el modelo económico: investigador, analista, contrario, auditor y coordinador.",
    cost: "Presupuesto bajo",
  },
  {
    id: "deep",
    title: "Profundo",
    body: "Cinco roles con los modelos fuertes en análisis y coordinación. Más coste, más matiz.",
    cost: "Presupuesto alto",
  },
]

export function Research() {
  const [params] = useSearchParams()
  const [ticker, setTicker] = useState((params.get("ticker") ?? "").toUpperCase())
  const [profile, setProfile] = useState("standard")
  const [budget, setBudget] = useState("0.50")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const { data: plan } = useAsync(() => researchApi.plan(profile), [profile])
  const { data, loading, error: listError, reload } = useAsync(() => researchApi.list(), [])
  const timer = useRef<number | null>(null)

  const active = (data?.items ?? []).some((job) => job.status === "running" || job.status === "queued")

  useEffect(() => {
    if (!active) return
    timer.current = window.setInterval(() => reload(), 3000)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [active, reload])

  const start = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const response = await researchApi.create(ticker.trim().toUpperCase(), profile, Number(budget) || undefined)
      setNotice(
        response.note ||
          `Investigación #${response.id} encolada con perfil ${response.profile}. Se ejecuta en el servidor.`,
      )
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo iniciar la investigación.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Centro de investigación</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Investigación</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          El orquestador reparte el trabajo entre roles, contrasta cada cifra con el expediente y
          conserva los desacuerdos. El presupuesto es un límite duro por trabajo.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.05fr_1fr]">
        <Card>
          <SectionHeader title="Nueva investigación" />
          <form className="space-y-4" onSubmit={start}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Ticker">
                <input
                  className="field font-mono uppercase"
                  value={ticker}
                  onChange={(event) => setTicker(event.target.value.toUpperCase())}
                  placeholder="AAPL"
                  maxLength={12}
                  required
                />
              </Field>
              <Field label="Presupuesto (USD)" hint={`Máximo ${plan?.max_budget_usd?.toFixed(2) ?? "5.00"} USD`}>
                <input
                  className="field"
                  type="number"
                  step="0.05"
                  min="0.05"
                  max={plan?.max_budget_usd ?? 5}
                  value={budget}
                  onChange={(event) => setBudget(event.target.value)}
                />
              </Field>
            </div>

            <div className="space-y-2">
              <span className="label">Perfil</span>
              {PROFILES.map((item) => (
                <label
                  key={item.id}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors ${
                    profile === item.id
                      ? "border-moss-600/40 bg-moss-100/40"
                      : "border-ink-900/10 bg-white/60 hover:border-ink-900/20"
                  } ${item.id !== "basic" && plan && !plan.ai_available ? "opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name="profile"
                    value={item.id}
                    checked={profile === item.id}
                    onChange={() => setProfile(item.id)}
                    className="mt-1"
                  />
                  <span>
                    <span className="flex items-center gap-2 text-sm font-medium text-ink-900">
                      {item.title}
                      <span className="text-[10px] uppercase tracking-wide text-ink-300">{item.cost}</span>
                    </span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">{item.body}</span>
                  </span>
                </label>
              ))}
            </div>

            {plan && !plan.ai_available ? (
              <Notice tone="warning">
                No hay proveedores de IA configurados. Puedes lanzar el perfil básico; el sistema no
                inventará las secciones cualitativas.
              </Notice>
            ) : null}

            {error ? <ErrorNotice message={error} /> : null}
            {notice ? <Notice tone="success">{notice}</Notice> : null}

            <button type="submit" className="btn-primary w-full" disabled={busy || !ticker.trim()}>
              {busy ? "Encolando…" : "Iniciar investigación"}
            </button>
            <p className="text-[11px] leading-relaxed text-ink-300">
              Coste máximo estimado del perfil:{" "}
              {plan?.plan.estimated_max_cost_usd != null
                ? `${plan.plan.estimated_max_cost_usd.toFixed(4)} USD`
                : "—"}
              . El trabajo se detiene al agotar el presupuesto y el informe parcial se guarda.
            </p>
          </form>
        </Card>

        <div className="space-y-4">
          <Card>
            <SectionHeader title="Plan del orquestador" subtitle="Roles y modelos que se ejecutarían." />
            {plan ? (
              plan.plan.roles.length ? (
                <ol className="space-y-2">
                  {plan.plan.roles.map((role, index) => (
                    <li key={role.role} className="flex items-start gap-3 text-sm">
                      <span className="mt-0.5 font-mono text-xs text-ink-300">{String(index + 1).padStart(2, "0")}</span>
                      <span>
                        <span className="text-ink-800">{role.label}</span>
                        <span className="ml-2 font-mono text-[11px] text-ink-300">{role.model}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-ink-500">Perfil básico: sin llamadas a modelos.</p>
              )
            ) : (
              <p className="text-sm text-ink-300">Cargando plan…</p>
            )}
          </Card>
          <Card>
            <p className="text-sm font-medium text-ink-800">Presupuesto del mes</p>
            {plan ? (
              <>
                <p className="mt-2 font-mono text-xl">
                  {plan.usage.used_usd.toFixed(2)} / {plan.usage.limit_usd.toFixed(2)} USD
                </p>
                <p className="mt-1 text-xs text-ink-300">
                  Quedan {plan.usage.remaining_usd.toFixed(2)} USD · {plan.usage.jobs} trabajo(s)
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-ink-300">—</p>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <SectionHeader
          title="Historial"
          subtitle="Los trabajos se ejecutan en el servidor; puedes cerrar la pestaña y volver después."
          action={
            <button type="button" className="btn-ghost text-xs" onClick={reload}>
              Actualizar
            </button>
          }
        />
        {listError ? <ErrorNotice message={listError} onRetry={reload} /> : null}
        {loading && !data ? (
          <p className="text-sm text-ink-300">Cargando…</p>
        ) : (data?.items.length ?? 0) === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-900/15 p-6 text-center text-sm text-ink-500">
            Sin investigaciones todavía.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Estado</th>
                <th>Perfil</th>
                <th className="text-right">Coste</th>
                <th className="text-right">Creada</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((job: Job) => {
                const status = statusLabel(job.status)
                return (
                  <tr key={job.id}>
                    <td className="font-mono">{job.ticker}</td>
                    <td>
                      <Badge tone={status.tone}>{status.text}</Badge>
                      <span className="ml-2 text-[11px] text-ink-300">{job.stage}</span>
                    </td>
                    <td className="text-xs uppercase tracking-wide text-ink-500">{job.profile}</td>
                    <td className="text-right font-mono text-xs">{job.cost_usd.toFixed(4)} USD</td>
                    <td className="text-right text-xs text-ink-300">{relative(job.created_at)}</td>
                    <td className="text-right">
                      <Link to={`/investigacion/${job.id}`} className="text-xs no-underline">
                        Ver
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  )
}
