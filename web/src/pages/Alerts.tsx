import { useMemo, useState } from "react"
import { alertsApi, marketsApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, EmptyState, ErrorNotice, Field, Notice, SectionHeader, Spinner, Table } from "../components/ui"

const KIND_HINTS: Record<string, string> = {
  price_change_pct: "Ventana en días configurada en la regla (por defecto 7).",
  fundamentals_change: "Compara el último reporte anual con el anterior.",
  data_stale: "Avisa cuando los datos dejan de actualizarse.",
  concentration_risk: "Requiere cartera con peso máximo por posición.",
}

export function Alerts() {
  const state = useAsync(() => alertsApi.state(), [])
  const events = useAsync(() => alertsApi.events(), [])
  const instruments = useAsync(() => marketsApi.instruments("", ""), [])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState({ kind: "", instrument_uid: "", threshold: "", window_days: "7" })

  const catalog = state.data?.catalog ?? []
  const selectedMeta = useMemo(() => catalog.find((item) => item.kind === form.kind) ?? null, [catalog, form.kind])

  const refresh = () => {
    state.reload()
    events.reload()
  }

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage(done)
      refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "La acción falló")
    } finally {
      setBusy(false)
    }
  }

  const createRule = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedMeta) return
    const config: Record<string, unknown> = {}
    if (form.kind === "price_change_pct") config.window_days = Number(form.window_days) || 7
    await run(
      () =>
        alertsApi.create({
          kind: form.kind,
          instrument_uid: selectedMeta.requires_instrument ? form.instrument_uid || null : null,
          threshold: selectedMeta.requires_threshold ? form.threshold : null,
          config,
        }),
      "Regla creada. Se evaluará tras cada actualización de datos.",
    )
  }

  const schedulerOn = (state.data?.scheduler.interval_minutes ?? 0) > 0

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Automatización</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Alertas</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Reglas sobre datos ya almacenados: precios, objetivos, fundamentales, desactualización y
          concentración. Nada sale de tu base salvo las actualizaciones de datos que actives.
        </p>
      </div>

      {errorBlock(state.error, state.reload)}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">Sin leer</p>
          <p className="stat-value mt-2">{state.data?.unread ?? "—"}</p>
        </Card>
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">Reglas activas</p>
          <p className="stat-value mt-2">{state.data?.rules.filter((rule) => rule.active).length ?? "—"}</p>
        </Card>
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">Planificador</p>
          <p className="stat-value mt-2">{schedulerOn ? "activo" : "por sync"}</p>
          <p className="mt-1 text-xs text-ink-500">
            {schedulerOn
              ? `Revisión cada ${state.data?.scheduler.interval_minutes} min`
              : "Se revisa tras cada actualización de datos"}
          </p>
        </Card>
      </div>

      {message ? <Notice tone="success">{message}</Notice> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <SectionHeader title="Nueva regla" subtitle="Umbral en la moneda del instrumento." />
          {state.loading && !state.data ? (
            <Spinner />
          ) : (
            <form className="space-y-4" onSubmit={createRule}>
              <Field label="Tipo de condición">
                <select
                  className="field"
                  value={form.kind}
                  onChange={(event) => setForm({ ...form, kind: event.target.value })}
                  required
                >
                  <option value="">Elige una…</option>
                  {catalog.map((item) => (
                    <option key={item.kind} value={item.kind}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>
              {selectedMeta?.requires_instrument ? (
                <Field label="Instrumento">
                  <select
                    className="field"
                    value={form.instrument_uid}
                    onChange={(event) => setForm({ ...form, instrument_uid: event.target.value })}
                    required
                  >
                    <option value="">Elige uno…</option>
                    {(instruments.data?.items ?? []).map((item) => (
                      <option key={item.uid} value={item.uid}>
                        {item.symbol} — {item.name}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : null}
              {selectedMeta?.requires_threshold ? (
                <Field
                  label={`Umbral (${selectedMeta.unit})`}
                  hint={KIND_HINTS[form.kind]}
                >
                  <input
                    className="field"
                    type="number"
                    step="any"
                    min="0"
                    value={form.threshold}
                    onChange={(event) => setForm({ ...form, threshold: event.target.value })}
                    required
                  />
                </Field>
              ) : null}
              {form.kind === "price_change_pct" ? (
                <Field label="Ventana (días)">
                  <input
                    className="field"
                    type="number"
                    min="1"
                    max="90"
                    value={form.window_days}
                    onChange={(event) => setForm({ ...form, window_days: event.target.value })}
                  />
                </Field>
              ) : null}
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? "Creando…" : "Crear regla"}
              </button>
            </form>
          )}
        </Card>

        <Card>
          <SectionHeader
            title="Reglas"
            subtitle="Las permanentes se deduplican por semana para no repetirse."
            action={
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  disabled={busy}
                  onClick={() => run(() => alertsApi.evaluate(), "Revisión completada.")}
                >
                  Revisar ahora
                </button>
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  disabled={busy || (state.data?.unread ?? 0) === 0}
                  onClick={() => run(() => alertsApi.readAll(), "Todo marcado como leído.")}
                >
                  Marcar leídas
                </button>
              </div>
            }
          />
          {(state.data?.rules.length ?? 0) === 0 && !state.loading ? (
            <EmptyState
              title="Sin reglas todavía"
              description="Crea una condición de precio, objetivo o cambio fundamental para que el sistema vigile por ti."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Condición</th>
                  <th>Instrumento</th>
                  <th>Umbral</th>
                  <th>Estado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(state.data?.rules ?? []).map((rule) => (
                  <tr key={rule.id}>
                    <td>{rule.label}</td>
                    <td className="font-mono text-xs">{rule.instrument_symbol ?? "—"}</td>
                    <td className="font-mono text-xs">{rule.threshold ?? "—"}</td>
                    <td>
                      <Badge tone={rule.active ? "fact" : "muted"}>
                        {rule.active ? "activa" : "pausada"}
                      </Badge>
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="text-xs font-semibold underline"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () => alertsApi.update(rule.id, { active: !rule.active }),
                            rule.active ? "Regla pausada." : "Regla reactivada.",
                          )
                        }
                      >
                        {rule.active ? "Pausar" : "Activar"}
                      </button>{" "}
                      <button
                        type="button"
                        className="text-xs font-semibold text-rust-600 underline"
                        disabled={busy}
                        onClick={() => run(() => alertsApi.remove(rule.id), "Regla eliminada.")}
                      >
                        Eliminar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

      <Card>
        <SectionHeader title="Historial" subtitle="Eventos detectados por el motor, con su procedencia." />
        {events.error ? <ErrorNotice message={events.error} onRetry={events.reload} /> : null}
        {events.loading && !events.data ? (
          <Spinner />
        ) : (events.data?.events.length ?? 0) === 0 ? (
          <EmptyState title="Sin alertas" description="Aún no se ha detectado ninguna condición cumplida." />
        ) : (
          <ul className="space-y-3">
            {(events.data?.events ?? []).map((event) => (
              <li
                key={event.id}
                className={`rounded-lg border px-4 py-3 text-sm ${
                  event.read_at ? "border-ink-900/10 bg-white/60" : "border-moss-600/30 bg-moss-100/60"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-ink-900">{event.title}</span>
                  <span className="flex items-center gap-2">
                    <Badge tone={event.severity === "warning" ? "warn" : "muted"}>{event.kind}</Badge>
                    <span className="text-xs text-ink-300">
                      {new Date(event.created_at).toLocaleString("es")}
                    </span>
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {Object.entries(event.detail)
                    .map(([key, value]) => `${key}: ${String(value)}`)
                    .join(" · ")}
                </p>
                {!event.read_at ? (
                  <button
                    type="button"
                    className="mt-2 text-xs font-semibold underline"
                    onClick={() => run(() => alertsApi.read(event.id), "Alerta leída.")}
                  >
                    Marcar leída
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function errorBlock(error: string | null, reload: () => void) {
  return error ? <ErrorNotice message={error} onRetry={reload} /> : null
}
