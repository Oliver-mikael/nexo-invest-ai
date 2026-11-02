import { useState } from "react"
import { boardApi, thesesApi, type ThesisStatus, type ThesisView } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, EmptyState, ErrorNotice, Field, Notice, SectionHeader, Spinner, Tabs } from "../components/ui"

const STATUS_LABEL: Record<string, string> = {
  open: "abierta",
  under_review: "en revisión",
  validated: "validada",
  invalidated: "invalidada",
  closed: "cerrada",
}

const STATUS_TONE: Record<string, "fact" | "ai" | "warn" | "muted"> = {
  open: "muted",
  under_review: "ai",
  validated: "fact",
  invalidated: "warn",
  closed: "muted",
}

const ALLOWED: Record<ThesisStatus, ThesisStatus[]> = {
  open: ["under_review", "closed"],
  under_review: ["open", "validated", "invalidated", "closed"],
  validated: ["closed", "under_review"],
  invalidated: ["closed", "under_review"],
  closed: [],
}

type Filter = "" | ThesisStatus

export function Theses() {
  const [filter, setFilter] = useState<Filter>("")
  const list = useAsync(() => thesesApi.list(filter || undefined), [filter])
  const [selected, setSelected] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Investigación</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Tesis de inversión</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Hipótesis versionadas con condiciones de invalidación explícitas. El motor solo sugiere:
          validar o invalidar lo decides tú.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Tabs<Filter>
          tabs={[
            { id: "", label: "Todas" },
            { id: "open", label: "Abiertas" },
            { id: "under_review", label: "En revisión" },
            { id: "validated", label: "Validadas" },
            { id: "invalidated", label: "Invalidadas" },
            { id: "closed", label: "Cerradas" },
          ]}
          value={filter}
          onChange={setFilter}
        />
        <button
          type="button"
          className="btn-primary ml-auto text-sm"
          onClick={() => setCreating((value) => !value)}
        >
          {creating ? "Cancelar" : "Nueva tesis"}
        </button>
        <button
          type="button"
          className="btn-ghost text-xs"
          onClick={async () => {
            try {
              await thesesApi.evaluate()
              list.reload()
            } catch {
              /* el listado se recarga igualmente al volver a montar */
            }
          }}
        >
          Revisar con el motor
        </button>
      </div>

      {creating ? <NewThesisForm onDone={() => { setCreating(false); list.reload() }} /> : null}
      {list.error ? <ErrorNotice message={list.error} onRetry={list.reload} /> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
        <Card>
          <SectionHeader title="Listado" subtitle={`${list.data?.theses.length ?? 0} tesis`} />
          {list.loading && !list.data ? (
            <Spinner />
          ) : (list.data?.theses.length ?? 0) === 0 ? (
            <EmptyState
              title="Sin tesis"
              description="Abre una hipótesis con sus condiciones de invalidación para seguirla en versiones."
            />
          ) : (
            <ul className="divide-y divide-ink-900/10">
              {(list.data?.theses ?? []).map((thesis) => (
                <li key={thesis.id}>
                  <button
                    type="button"
                    className={`flex w-full items-start justify-between gap-3 py-3 text-left ${
                      selected === thesis.id ? "opacity-100" : "opacity-90 hover:opacity-100"
                    }`}
                    onClick={() => setSelected(thesis.id)}
                  >
                    <div>
                      <p className="text-sm font-semibold text-ink-900">{thesis.title}</p>
                      <p className="mt-0.5 font-mono text-xs text-ink-500">
                        {thesis.instrument?.symbol ?? "—"} · {thesis.version_count} versión(es)
                      </p>
                    </div>
                    <Badge tone={STATUS_TONE[thesis.status]}>{STATUS_LABEL[thesis.status]}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {selected === null ? (
          <Card>
            <EmptyState
              title="Selecciona una tesis"
              description="Verás su hipótesis vigente, el historial de versiones, los sucesos del motor y las transiciones de estado permitidas."
            />
          </Card>
        ) : (
          <ThesisDetail
            key={selected}
            id={selected}
            onChanged={() => list.reload()}
            onDeleted={() => { setSelected(null); list.reload() }}
          />
        )}
      </div>
    </div>
  )
}

function NewThesisForm({ onDone }: { onDone: () => void }) {
  const instruments = useAsync(() => boardApi.watchlist(), [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    instrument_uid: "",
    title: "",
    hypothesis: "",
    horizon: "medium",
    condition_price: "",
    condition_text: "",
  })

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const conditions: { type: string; price?: number; text?: string; note?: string }[] = []
      if (form.condition_price) {
        conditions.push({ type: "price_below", price: Number(form.condition_price), note: "invalidación por precio" })
      }
      if (form.condition_text.trim()) {
        conditions.push({ type: "text", text: form.condition_text.trim(), note: "invalidación textual" })
      }
      await thesesApi.create({
        instrument_uid: form.instrument_uid,
        horizon: form.horizon,
        title: form.title.trim(),
        hypothesis: form.hypothesis.trim(),
        invalidation_conditions: conditions,
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la tesis")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <SectionHeader title="Nueva tesis" subtitle="Toda tesis empieza abierta; el motor solo registra indicios." />
      {error ? <Notice tone="error">{error}</Notice> : null}
      <form className="grid gap-4 md:grid-cols-2" onSubmit={submit}>
        <Field label="Instrumento" hint="Añade el instrumento a tu seguimiento si aún no está.">
          <select
            className="field"
            value={form.instrument_uid}
            onChange={(event) => setForm({ ...form, instrument_uid: event.target.value })}
            required
          >
            <option value="">Elige uno…</option>
            {(instruments.data?.items ?? []).map((item) => (
              <option key={item.instrument_uid} value={item.instrument_uid}>
                {item.symbol} — {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Horizonte (etiqueta, no promesa)">
          <select
            className="field"
            value={form.horizon}
            onChange={(event) => setForm({ ...form, horizon: event.target.value })}
          >
            <option value="short">corto</option>
            <option value="medium">medio</option>
            <option value="long">largo</option>
          </select>
        </Field>
        <Field label="Título">
          <input
            className="field"
            value={form.title}
            onChange={(event) => setForm({ ...form, title: event.target.value })}
            minLength={8}
            required
          />
        </Field>
        <Field label="Condición de precio (price_below, opcional)">
          <input
            className="field"
            type="number"
            step="any"
            min="0"
            value={form.condition_price}
            onChange={(event) => setForm({ ...form, condition_price: event.target.value })}
            placeholder="90"
          />
        </Field>
        <div className="md:col-span-2">
          <Field label="Hipótesis">
            <textarea
              className="field min-h-[96px]"
              value={form.hypothesis}
              onChange={(event) => setForm({ ...form, hypothesis: event.target.value })}
              minLength={20}
              required
            />
          </Field>
        </div>
        <div className="md:col-span-2">
          <Field label="Condición textual de invalidación (opcional)">
            <input
              className="field"
              value={form.condition_text}
              onChange={(event) => setForm({ ...form, condition_text: event.target.value })}
              placeholder="Margen bruto bajo 30 % en dos reportes seguidos"
            />
          </Field>
        </div>
        <div>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Creando…" : "Abrir tesis"}
          </button>
        </div>
      </form>
    </Card>
  )
}

function ThesisDetail({
  id,
  onChanged,
  onDeleted,
}: {
  id: number
  onChanged: () => void
  onDeleted: () => void
}) {
  const detail = useAsync(() => thesesApi.get(id), [id])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState("")

  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
      setMessage(done)
      detail.reload()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : "La acción falló")
    } finally {
      setBusy(false)
    }
  }

  if (detail.error) return <ErrorNotice message={detail.error} onRetry={detail.reload} />
  const thesis: ThesisView | null = detail.data
  if (!thesis) return <Card><Spinner /></Card>

  const nextStatuses = ALLOWED[thesis.status]

  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader
          title={thesis.title}
          subtitle={`${thesis.instrument?.symbol ?? ""} · horizonte ${thesis.horizon} · incertidumbre ${thesis.uncertainty_level}`}
          action={<Badge tone={STATUS_TONE[thesis.status]}>{STATUS_LABEL[thesis.status]}</Badge>}
        />
        {message ? <Notice tone="success">{message}</Notice> : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        <p className="text-sm leading-relaxed text-ink-700">{thesis.hypothesis}</p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
              Condiciones de invalidación
            </p>
            <ul className="mt-2 space-y-1 text-sm text-ink-600">
              {thesis.invalidation_conditions.map((condition, index) => (
                <li key={index} className="rounded-md border border-ink-900/10 px-3 py-2">
                  {condition.type === "price_below"
                    ? `Precio por debajo de ${String(condition.price)}`
                    : String(condition.text ?? condition.type)}
                </li>
              ))}
              {thesis.invalidation_conditions.length === 0 ? (
                <li className="text-xs text-ink-300">Sin condiciones registradas.</li>
              ) : null}
            </ul>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">Objetivos</p>
            <p className="mt-2 font-mono text-sm text-ink-600">
              entrada {thesis.entry_target ?? "—"} · salida {thesis.exit_target ?? "—"}
            </p>
            <p className="mt-3 text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">
              Información que falta
            </p>
            <p className="mt-1 text-sm text-ink-500">
              {thesis.missing_info.length ? thesis.missing_info.join(" · ") : "no declarada"}
            </p>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <Field label="Nota (obligatoria al validar/invalidar)">
            <input
              className="field w-64"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Por qué cambia el estado"
            />
          </Field>
          {nextStatuses.map((status) => (
            <button
              key={status}
              type="button"
              className={status === "validated" ? "btn-primary text-sm" : "btn-ghost text-sm"}
              disabled={busy || ((status === "validated" || status === "invalidated") && !note.trim())}
              onClick={() =>
                act(() => thesesApi.setStatus(id, status, note.trim()), `Estado: ${STATUS_LABEL[status]}.`)
              }
            >
              → {STATUS_LABEL[status]}
            </button>
          ))}
          <button
            type="button"
            className="btn-ghost text-sm"
            disabled={busy}
            onClick={() =>
              act(() => thesesApi.addVersion(id, { note: note.trim() || "Revisión manual" }), "Nueva versión registrada.")
            }
          >
            Guardar versión
          </button>
          <button
            type="button"
            className="text-xs font-semibold text-rust-600 underline"
            disabled={busy}
            onClick={() => act(() => thesesApi.remove(id), "Tesis eliminada.").then(onDeleted)}
          >
            Eliminar
          </button>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
          Transiciones permitidas desde {STATUS_LABEL[thesis.status]}:{" "}
          {nextStatuses.length ? nextStatuses.map((status) => STATUS_LABEL[status]).join(", ") : "ninguna (estado final)"}.
        </p>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <SectionHeader title="Versiones" subtitle={`${thesis.version_count} registradas`} />
          <ul className="space-y-3">
            {(thesis.versions ?? []).map((version) => (
              <li key={version.number} className="rounded-lg border border-ink-900/10 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold">v{version.number}</span>
                  <span className="text-xs text-ink-300">
                    {new Date(version.created_at).toLocaleDateString("es")}
                  </span>
                </div>
                <p className="mt-1 text-sm text-ink-600">{version.hypothesis}</p>
                {version.note ? <p className="mt-1 text-xs text-ink-400">{version.note}</p> : null}
              </li>
            ))}
            {(thesis.versions ?? []).length === 0 ? (
              <li className="text-sm text-ink-400">Sin versiones.</li>
            ) : null}
          </ul>
        </Card>

        <Card>
          <SectionHeader title="Sucesos" subtitle="Del motor (deduplicados) y tuyos" />
          <ul className="space-y-2">
            {(thesis.events ?? []).map((event) => (
              <li key={event.id} className="rounded-lg border border-ink-900/10 px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{event.kind}</span>
                  <span className="text-xs text-ink-300">
                    {event.detected_by === "engine" ? "motor" : "usuario"} ·{" "}
                    {new Date(event.created_at).toLocaleString("es")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {Object.entries(event.payload)
                    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
                    .join(" · ")}
                </p>
              </li>
            ))}
            {(thesis.events ?? []).length === 0 ? (
              <li className="text-sm text-ink-400">Sin sucesos registrados.</li>
            ) : null}
          </ul>
        </Card>
      </div>
    </div>
  )
}
