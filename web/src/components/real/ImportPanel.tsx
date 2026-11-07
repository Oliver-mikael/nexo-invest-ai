import { useState } from "react"
import { ApiError, realApi, type ImportPreview } from "../../lib/api"
import { Card, ErrorNotice, Field, Notice, SectionHeader, Table } from "../ui"

export function ImportPanel({ accountId, onImported }: { accountId: number; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [mapping, setMapping] = useState("")
  const [dateOrder, setDateOrder] = useState("dmy")
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [allowPartial, setAllowPartial] = useState(false)

  const runPreview = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    setPreview(null)
    try {
      const data = await realApi.previewImport(accountId, file, mapping.trim(), dateOrder)
      setPreview(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo leer el archivo")
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      const data = await realApi.confirmImport(accountId, preview.id, allowPartial)
      setResult(
        `Importación confirmada: ${data.created} movimiento(s) nuevo(s), ${data.skipped_duplicates} duplicado(s) omitido(s), ${data.errors.length} fila(s) con error.`,
      )
      setPreview({ ...preview, status: "confirmed" })
      onImported()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo confirmar la importación")
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    if (!preview) return
    setBusy(true)
    try {
      await realApi.discardImport(accountId, preview.id)
      setPreview(null)
      setResult("Previsualización descartada. No se registró nada.")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo descartar")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader
          title="Importar CSV o XLSX"
          subtitle="Primero se valida y se muestra una vista previa; nada se registra hasta que confirmes."
        />
        <form className="space-y-3" onSubmit={runPreview}>
          <Field label="Archivo" hint="Máximo 5 MB y 2.000 filas. CSV, TXT o XLSX.">
            <input
              className="field file:mr-3 file:rounded-md file:border-0 file:bg-ink-900 file:px-3 file:py-1.5 file:text-xs file:text-paper"
              type="file"
              accept=".csv,.txt,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null)
                setPreview(null)
                setResult(null)
              }}
              required
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Orden de fecha" hint="Si el archivo usa 03/04/2024, ¿es 3 de abril o 4 de marzo?">
              <select className="field" value={dateOrder} onChange={(event) => setDateOrder(event.target.value)}>
                <option value="dmy">Día/mes/año (es-*)</option>
                <option value="mdy">Mes/día/año (en-US)</option>
              </select>
            </Field>
            <Field label="Mapeo manual (opcional)" hint='JSON: {"date":"Fecha","type":"Operación",…}'>
              <input
                className="field font-mono text-xs"
                value={mapping}
                onChange={(event) => setMapping(event.target.value)}
                placeholder='{"symbol":"Ticker"}'
              />
            </Field>
          </div>
          <button type="submit" className="btn-primary" disabled={busy || !file}>
            {busy ? "Leyendo…" : "Previsualizar"}
          </button>
        </form>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
          Columnas reconocidas: fecha, tipo, símbolo, ISIN, cantidad, precio, importe, comisión,
          impuesto, moneda, tipo de cambio, notas y referencia externa. El archivo original no se
          guarda en esta fase.
        </p>
      </Card>

      {error ? <ErrorNotice message={error} /> : null}
      {result ? <Notice tone="success">{result}</Notice> : null}

      {preview ? (
        <Card>
          <SectionHeader
            title={`Vista previa · ${preview.filename}`}
            subtitle={`${preview.total_rows} fila(s) · ${preview.valid_rows} válida(s) · ${preview.duplicate_rows} duplicada(s) · ${preview.error_rows} con error`}
            action={
              preview.status === "preview" ? (
                <div className="flex items-center gap-2">
                  <button type="button" className="btn-ghost text-xs" onClick={discard} disabled={busy}>
                    Descartar
                  </button>
                  <button type="button" className="btn-primary text-xs" onClick={confirm} disabled={busy || (!preview.ready_to_confirm && !allowPartial)}>
                    Confirmar importación
                  </button>
                </div>
              ) : (
                <span className="chip-fact">confirmada</span>
              )
            }
          />
          {!preview.ready_to_confirm && preview.status === "preview" ? (
            <div className="mb-3 space-y-2">
              <Notice tone="warning">
                Hay filas con errores. Corrige el archivo o marca la casilla para importar solo las
                filas válidas.
              </Notice>
              <label className="flex items-center gap-2 text-xs text-ink-500">
                <input type="checkbox" checked={allowPartial} onChange={(event) => setAllowPartial(event.target.checked)} />
                Importar solo las filas válidas (importación parcial)
              </label>
            </div>
          ) : null}
          <Table>
            <thead>
              <tr>
                <th>Fila</th>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Símbolo</th>
                <th className="text-right">Cantidad</th>
                <th className="text-right">Precio</th>
                <th className="text-right">Importe</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row) => (
                <tr key={row.row}>
                  <td className="font-mono text-xs text-ink-300">{row.row}</td>
                  <td className="font-mono text-xs">{row.payload?.movement_date ?? "—"}</td>
                  <td className="text-xs">{row.payload?.movement_type ?? "—"}</td>
                  <td className="font-mono text-xs">
                    {row.payload?.instrument_uid ? row.raw.simbolo || row.raw.symbol || "—" : "—"}
                  </td>
                  <td className="text-right font-mono text-xs">{row.payload?.quantity ?? "—"}</td>
                  <td className="text-right font-mono text-xs">{row.payload?.price ?? "—"}</td>
                  <td className="text-right font-mono text-xs">{row.payload?.amount ?? "—"}</td>
                  <td className="text-xs">
                    {row.errors.length ? (
                      <span className="text-rust-600">{row.errors[0]}</span>
                    ) : row.duplicate ? (
                      <span className="text-amber-600">{row.duplicate_reason}</span>
                    ) : (
                      <span className="text-moss-600">válida</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          {preview.total_rows > preview.rows_returned ? (
            <p className="mt-2 text-xs text-ink-300">
              Se muestran {preview.rows_returned} de {preview.total_rows} filas. La importación usa el
              archivo normalizado completo guardado en la previsualización.
            </p>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}
