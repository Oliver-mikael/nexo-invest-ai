import { useEffect, useMemo, useState } from "react"
import { ApiError, realApi, type Instrument } from "../../lib/api"
import { Field } from "../ui"

const TYPES = [
  { id: "deposit", label: "Depósito", instrument: false, amount: true },
  { id: "withdrawal", label: "Retiro", instrument: false, amount: true },
  { id: "buy", label: "Compra", instrument: true, amount: false },
  { id: "sell", label: "Venta", instrument: true, amount: false },
  { id: "dividend", label: "Dividendo", instrument: true, amount: true },
  { id: "fee", label: "Comisión", instrument: false, amount: true },
  { id: "tax", label: "Impuesto", instrument: false, amount: true },
  { id: "adjustment", label: "Ajuste de conciliación", instrument: false, amount: true },
  { id: "split", label: "Split (variación de títulos)", instrument: true, amount: false },
  { id: "transfer_in", label: "Traspaso entrante (efectivo)", instrument: false, amount: true },
  { id: "transfer_out", label: "Traspaso saliente (efectivo)", instrument: false, amount: true },
]

export type MovementDefaults = {
  movement_type?: string
  movement_date?: string
  instrument_uid?: string
  quantity?: string
  price?: string
  amount?: string
  fee?: string
  tax?: string
  currency?: string
  notes?: string
}

export function MovementForm({
  accountId,
  baseCurrency,
  instruments,
  defaults,
  onCreated,
  submitLabel = "Registrar movimiento",
  submitOverride,
}: {
  accountId: number
  baseCurrency: string
  instruments: Instrument[]
  defaults?: MovementDefaults
  onCreated: () => void
  submitLabel?: string
  submitOverride?: (payload: Record<string, unknown>) => Promise<void>
}) {
  const initial = useMemo(
    () => ({
      movement_type: defaults?.movement_type ?? "buy",
      movement_date: defaults?.movement_date ?? new Date().toISOString().slice(0, 10),
      instrument_uid: defaults?.instrument_uid ?? "",
      quantity: defaults?.quantity ?? "",
      price: defaults?.price ?? "",
      amount: defaults?.amount ?? "",
      fee: defaults?.fee ?? "",
      tax: defaults?.tax ?? "",
      currency: defaults?.currency ?? baseCurrency,
      fx_rate: "",
      fx_source: "",
      notes: defaults?.notes ?? "",
    }),
    // El formulario se reinicia cuando cambia la cuenta o el documento de origen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [defaults, baseCurrency, accountId],
  )
  const [form, setForm] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  useEffect(() => setForm(initial), [initial, accountId])

  const definition = TYPES.find((item) => item.id === form.movement_type) ?? TYPES[0]
  const instrument = instruments.find((item) => item.uid === form.instrument_uid)
  const effectiveCurrency = instrument?.currency ?? form.currency ?? baseCurrency
  const needsFx = effectiveCurrency !== baseCurrency
  const tradeFields = form.movement_type === "buy" || form.movement_type === "sell"
  const showCosts = ["buy", "sell", "dividend", "adjustment"].includes(form.movement_type)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setOk(null)
    try {
      const payload: Record<string, unknown> = {
        movement_type: form.movement_type,
        movement_date: form.movement_date,
        quantity: form.quantity || "0",
        price: form.price || "0",
        amount: form.amount || "0",
        fee: form.fee || "0",
        tax: form.tax || "0",
        currency: effectiveCurrency,
        notes: form.notes,
      }
      if (definition.instrument) payload.instrument_uid = form.instrument_uid
      if (needsFx) {
        if (!form.fx_rate || !form.fx_source.trim()) {
          throw new Error("Indica el tipo de cambio histórico y su fuente.")
        }
        payload.fx_rate = form.fx_rate
        payload.fx_source = form.fx_source
      }
      if (submitOverride) {
        await submitOverride(payload)
      } else {
        await realApi.createMovement(accountId, payload)
      }
      setOk("Movimiento registrado y validado contra el libro completo.")
      setForm({
        ...initial,
        movement_type: form.movement_type,
        movement_date: form.movement_date,
        currency: baseCurrency,
      })
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "No se pudo registrar")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Tipo">
          <select
            className="field"
            value={form.movement_type}
            onChange={(event) =>
              setForm({
                ...form,
                movement_type: event.target.value,
                instrument_uid: "",
                amount: "",
                quantity: "",
                price: "",
              })
            }
          >
            {TYPES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Fecha">
          <input
            className="field"
            type="date"
            value={form.movement_date}
            onChange={(event) => setForm({ ...form, movement_date: event.target.value })}
            required
          />
        </Field>
      </div>

      {definition.instrument ? (
        <Field
          label="Instrumento"
          hint={
            instruments.length
              ? "El instrumento define la moneda y el mercado; no se usa el ticker como identificador global."
              : "Crea primero un instrumento en la pestaña Resumen."
          }
        >
          <select
            className="field"
            value={form.instrument_uid}
            onChange={(event) => {
              const selected = instruments.find((item) => item.uid === event.target.value)
              setForm({
                ...form,
                instrument_uid: event.target.value,
                currency: selected?.currency ?? baseCurrency,
              })
            }}
            required
          >
            <option value="">Selecciona instrumento…</option>
            {instruments.map((item) => (
              <option key={item.uid} value={item.uid}>
                {item.symbol} · {item.market} · {item.currency}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {tradeFields ? (
          <>
            <Field label="Cantidad">
              <input
                className="field font-mono"
                inputMode="decimal"
                value={form.quantity}
                onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                required
              />
            </Field>
            <Field label="Precio unitario">
              <input
                className="field font-mono"
                inputMode="decimal"
                value={form.price}
                onChange={(event) => setForm({ ...form, price: event.target.value })}
                required
              />
            </Field>
          </>
        ) : null}
        {form.movement_type === "split" ? (
          <Field label="Variación de títulos" hint="Positiva para split; negativa para contrasplit.">
            <input
              className="field font-mono"
              inputMode="decimal"
              value={form.quantity}
              onChange={(event) => setForm({ ...form, quantity: event.target.value })}
              required
            />
          </Field>
        ) : null}
        {definition.amount ? (
          <Field
            label={form.movement_type === "dividend" ? "Importe bruto" : "Importe"}
            hint={form.movement_type === "adjustment" ? "Puede ser negativo para conciliar." : undefined}
          >
            <input
              className="field font-mono"
              inputMode="decimal"
              value={form.amount}
              onChange={(event) => setForm({ ...form, amount: event.target.value })}
              required
            />
          </Field>
        ) : null}
        {showCosts ? (
          <>
            <Field label="Comisión">
              <input
                className="field font-mono"
                inputMode="decimal"
                value={form.fee}
                onChange={(event) => setForm({ ...form, fee: event.target.value })}
              />
            </Field>
            <Field label="Impuesto / retención">
              <input
                className="field font-mono"
                inputMode="decimal"
                value={form.tax}
                onChange={(event) => setForm({ ...form, tax: event.target.value })}
              />
            </Field>
          </>
        ) : null}
        <Field label="Moneda">
          <input
            className="field font-mono uppercase"
            value={effectiveCurrency}
            readOnly={Boolean(instrument)}
            onChange={(event) => setForm({ ...form, currency: event.target.value.toUpperCase() })}
            maxLength={3}
            required
          />
        </Field>
      </div>

      {needsFx ? (
        <div className="grid gap-3 rounded-lg border border-amber-600/20 bg-amber-100/40 p-3 sm:grid-cols-2">
          <Field
            label={`Tipo de cambio ${effectiveCurrency}/${baseCurrency}`}
            hint="Unidades de moneda base por una unidad de la moneda del movimiento."
          >
            <input
              className="field font-mono"
              inputMode="decimal"
              value={form.fx_rate}
              onChange={(event) => setForm({ ...form, fx_rate: event.target.value })}
              required
            />
          </Field>
          <Field label="Fuente del cambio">
            <input
              className="field"
              value={form.fx_source}
              onChange={(event) => setForm({ ...form, fx_source: event.target.value })}
              placeholder="broker, banco central, extracto…"
              required
            />
          </Field>
        </div>
      ) : null}

      <Field label="Notas">
        <textarea
          className="field min-h-[60px]"
          value={form.notes}
          onChange={(event) => setForm({ ...form, notes: event.target.value })}
          maxLength={4000}
        />
      </Field>

      {error ? <p className="text-sm text-rust-600">{error}</p> : null}
      {ok ? <p className="text-sm text-moss-600">{ok}</p> : null}
      <button type="submit" className="btn-primary w-full" disabled={busy}>
        {busy ? "Validando…" : submitLabel}
      </button>
    </form>
  )
}
