import { useEffect, useState } from "react"
import { systemApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Field, Notice, SectionHeader, Table } from "../components/ui"
import { useAuth } from "../lib/auth"

export function Settings() {
  const { user } = useAuth()
  const { data, loading, error, reload } = useAsync(() => systemApi.settings(), [])
  const [form, setForm] = useState({
    ai_profile: "standard",
    monthly_budget_usd: "10",
    default_forecast_years: "5",
    preferred_provider: "",
    benchmark: "SPY",
  })
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!data) return
    setForm({
      ai_profile: data.ai_profile,
      monthly_budget_usd: String(data.monthly_budget_usd),
      default_forecast_years: String(data.default_forecast_years),
      preferred_provider: data.preferred_provider,
      benchmark: data.benchmark,
    })
  }, [data])

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setSaved(false)
    setSaveError(null)
    try {
      await systemApi.updateSettings({
        ai_profile: form.ai_profile,
        monthly_budget_usd: Number(form.monthly_budget_usd),
        default_forecast_years: Number(form.default_forecast_years),
        preferred_provider: form.preferred_provider,
        benchmark: form.benchmark.toUpperCase(),
      })
      setSaved(true)
      reload()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "No se pudo guardar")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Cuenta</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Ajustes</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Preferencias de análisis, presupuesto mensual de IA y estado de los proveedores. Las claves
          de los proveedores viven solo en el servidor: nunca llegan al navegador.
        </p>
      </div>

      {error ? <ErrorNotice message={error} onRetry={reload} /> : null}

      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <Card>
          <SectionHeader title="Preferencias" subtitle="Se aplican a las nuevas investigaciones." />
          {loading && !data ? (
            <p className="text-sm text-ink-300">Cargando…</p>
          ) : (
            <form className="space-y-4" onSubmit={save}>
              <Field label="Perfil de IA por defecto">
                <select
                  className="field"
                  value={form.ai_profile}
                  onChange={(event) => setForm({ ...form, ai_profile: event.target.value })}
                >
                  <option value="basic">Básico (sin IA)</option>
                  <option value="standard">Estándar</option>
                  <option value="deep">Profundo</option>
                </select>
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Presupuesto mensual (USD)" hint="Límite duro para trabajos con IA.">
                  <input
                    className="field"
                    type="number"
                    min="0"
                    step="1"
                    value={form.monthly_budget_usd}
                    onChange={(event) => setForm({ ...form, monthly_budget_usd: event.target.value })}
                  />
                </Field>
                <Field label="Años de proyección">
                  <input
                    className="field"
                    type="number"
                    min="1"
                    max="15"
                    value={form.default_forecast_years}
                    onChange={(event) => setForm({ ...form, default_forecast_years: event.target.value })}
                  />
                </Field>
                <Field label="Proveedor preferido" hint="Vacío = el primero disponible.">
                  <select
                    className="field"
                    value={form.preferred_provider}
                    onChange={(event) => setForm({ ...form, preferred_provider: event.target.value })}
                  >
                    <option value="">Automático</option>
                    {(data?.providers ?? []).filter((provider) => provider.configured).map((provider) => (
                      <option key={provider.name} value={provider.name}>
                        {provider.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Benchmark de la cartera">
                  <input
                    className="field font-mono uppercase"
                    value={form.benchmark}
                    onChange={(event) => setForm({ ...form, benchmark: event.target.value })}
                    maxLength={16}
                  />
                </Field>
              </div>
              {saveError ? <ErrorNotice message={saveError} /> : null}
              {saved ? <Notice tone="success">Preferencias guardadas.</Notice> : null}
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? "Guardando…" : "Guardar cambios"}
              </button>
            </form>
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionHeader title="Cuenta" />
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Nombre</dt>
                <dd className="text-ink-800">{user?.display_name || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Correo</dt>
                <dd className="truncate text-ink-800">{user?.email}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Rol</dt>
                <dd className="text-ink-800">{user?.role}</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs leading-relaxed text-ink-300">
              Las sesiones caducan y se guardan hasheadas en el servidor. Cerrar sesión revoca el
              token actual.
            </p>
          </Card>

          <Card>
            <SectionHeader title="Consumo del mes" />
            {data ? (
              <>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <p className="font-mono text-lg">{data.usage.used_usd.toFixed(2)}</p>
                    <p className="text-[10px] uppercase tracking-wide text-ink-300">USD usados</p>
                  </div>
                  <div>
                    <p className="font-mono text-lg">{data.usage.limit_usd.toFixed(2)}</p>
                    <p className="text-[10px] uppercase tracking-wide text-ink-300">límite</p>
                  </div>
                  <div>
                    <p className="font-mono text-lg">{data.usage.jobs}</p>
                    <p className="text-[10px] uppercase tracking-wide text-ink-300">trabajos</p>
                  </div>
                </div>
                <p className="mt-3 text-xs text-ink-300">
                  Periodo {data.usage.period} · {data.usage.tokens_in + data.usage.tokens_out} tokens.
                </p>
              </>
            ) : (
              <p className="text-sm text-ink-300">—</p>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <SectionHeader
          title="Proveedores de IA"
          subtitle="Configurados en el servidor mediante variables de entorno. Aquí solo se muestra su estado."
        />
        <Table>
          <thead>
            <tr>
              <th>Proveedor</th>
              <th>Tipo</th>
              <th>Estado</th>
              <th>Modelos</th>
            </tr>
          </thead>
          <tbody>
            {(data?.providers ?? []).length === 0 ? (
              <tr>
                <td colSpan={4} className="text-sm text-ink-500">
                  Sin proveedores. El sistema funciona en modo básico: motor y procedencia, sin
                  análisis cualitativo.
                </td>
              </tr>
            ) : (
              (data?.providers ?? []).map((provider) => (
                <tr key={provider.name}>
                  <td className="font-medium">{provider.name}</td>
                  <td className="text-xs uppercase tracking-wide text-ink-500">{provider.kind}</td>
                  <td>
                    <Badge tone={provider.configured ? "fact" : "muted"}>
                      {provider.configured ? "configurado" : "sin clave"}
                    </Badge>
                  </td>
                  <td className="font-mono text-xs text-ink-500">{provider.models.join(", ") || "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
        <Notice tone="info">
          Para añadir un proveedor, define en el servidor `NEXO_AI_OPENAI_KEY`, `NEXO_AI_ANTHROPIC_KEY`,
          `NEXO_AI_GEMINI_KEY` o `NEXO_AI_LOCAL_BASE_URL`. El navegador no recibe ninguna clave.
        </Notice>
      </Card>
    </div>
  )
}
