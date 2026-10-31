import { useCallback, useEffect, useMemo, useState } from "react"
import { ApiError, realApi, type DocumentRecord, type Instrument } from "../../lib/api"
import { shortDate } from "../../lib/format"
import { Card, ErrorNotice, Field, Notice, SectionHeader } from "../ui"
import { MovementForm, type MovementDefaults } from "./MovementForm"

function defaultsFromDocument(document: DocumentRecord, instruments: Instrument[]): MovementDefaults {
  const fields = document.extraction.fields ?? {}
  const symbol = (fields.symbol ?? "").toUpperCase()
  const instrument = instruments.find((item) => item.symbol.toUpperCase() === symbol)
  return {
    movement_type: fields.movement_type ?? "buy",
    movement_date: fields.movement_date ?? new Date().toISOString().slice(0, 10),
    instrument_uid: instrument?.uid ?? "",
    quantity: fields.quantity ?? "",
    price: fields.price ?? "",
    amount: fields.amount ?? "",
    fee: fields.fee ?? "",
    tax: fields.tax ?? "",
    currency: fields.currency || instrument?.currency || "USD",
    notes: `Extraído del documento #${document.id} y revisado por el usuario.`,
  }
}

export function DocumentsPanel({
  accountId,
  baseCurrency,
  instruments,
  onConfirmed,
}: {
  accountId: number
  baseCurrency: string
  instruments: Instrument[]
  onConfirmed: () => void
}) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | "upload" | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [version, setVersion] = useState(0)
  const [openDocument, setOpenDocument] = useState<number | null>(null)

  const reload = useCallback(() => setVersion((value) => value + 1), [])

  useEffect(() => {
    let active = true
    setLoading(true)
    realApi
      .documents(accountId)
      .then((data) => {
        if (!active) return
        setDocuments(data.items)
        setError(null)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : "No se pudieron cargar los documentos")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [accountId, version])

  const upload = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) return
    setBusy("upload")
    setError(null)
    try {
      await realApi.uploadDocument(file, accountId)
      setFile(null)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo subir el documento")
    } finally {
      setBusy(null)
    }
  }

  const extract = async (document: DocumentRecord) => {
    setBusy(document.id)
    setError(null)
    try {
      await realApi.extractDocument(document.id)
      setOpenDocument(document.id)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo extraer el texto")
    } finally {
      setBusy(null)
    }
  }

  const download = async (document: DocumentRecord) => {
    setBusy(document.id)
    setError(null)
    try {
      const blob = await realApi.downloadDocument(document.id)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement("a")
      anchor.href = url
      anchor.download = document.filename
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo descargar el documento")
    } finally {
      setBusy(null)
    }
  }

  const remove = async (document: DocumentRecord) => {
    if (!window.confirm("¿Eliminar este documento? Solo se puede si no respalda un movimiento.")) return
    setBusy(document.id)
    setError(null)
    try {
      await realApi.deleteDocument(document.id)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo eliminar")
    } finally {
      setBusy(null)
    }
  }

  const selected = useMemo(
    () => documents.find((document) => document.id === openDocument) ?? null,
    [documents, openDocument],
  )
  const confirmDefaults = useMemo(
    () => (selected ? defaultsFromDocument(selected, instruments) : undefined),
    [selected, instruments],
  )

  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader
          title="Documentos privados"
          subtitle="Capturas, facturas o extractos PDF. El OCR se ejecuta en el servidor; el archivo no se envía a terceros."
        />
        <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={upload}>
          <div className="flex-1">
            <Field label="Documento" hint="JPEG, PNG, WebP o PDF. Máximo 10 MB.">
              <input
                className="field file:mr-3 file:rounded-md file:border-0 file:bg-ink-900 file:px-3 file:py-1.5 file:text-xs file:text-paper"
                type="file"
                accept="image/jpeg,image/png,image/webp,application/pdf"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                required
              />
            </Field>
          </div>
          <button type="submit" className="btn-primary" disabled={busy === "upload" || !file}>
            {busy === "upload" ? "Subiendo…" : "Subir"}
          </button>
        </form>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-300">
          El OCR local requiere Tesseract en el servidor. Si no está instalado, la API lo indica y
          no simula ninguna extracción. La IA no registra movimientos: siempre revisas y confirmas.
        </p>
      </Card>

      {error ? <ErrorNotice message={error} /> : null}
      {loading ? <p className="text-sm text-ink-500">Cargando documentos…</p> : null}

      {!loading && documents.length === 0 ? (
        <Notice tone="info">Todavía no hay documentos en esta cuenta.</Notice>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {documents.map((document) => (
          <Card key={document.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink-900">{document.filename}</p>
                <p className="mt-1 text-[11px] text-ink-300">
                  {document.content_type} · {(document.size_bytes / 1024).toFixed(0)} KB ·{" "}
                  {shortDate(document.created_at)} · {document.status}
                </p>
              </div>
              <span className="chip-muted shrink-0">{document.id}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="btn-ghost text-xs" onClick={() => extract(document)} disabled={busy === document.id}>
                {busy === document.id ? "Procesando…" : document.extraction.text ? "Volver a extraer" : "Extraer con OCR"}
              </button>
              {document.extraction.fields ? (
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={() => setOpenDocument(openDocument === document.id ? null : document.id)}
                >
                  Revisar campos
                </button>
              ) : null}
              <button type="button" className="btn-ghost text-xs" onClick={() => download(document)}>
                Descargar
              </button>
              <button type="button" className="btn-danger text-xs" onClick={() => remove(document)}>
                Eliminar
              </button>
            </div>
            {document.extraction.warnings ? (
              <p className="mt-3 text-[11px] text-amber-600">
                {Array.isArray(document.extraction.warnings)
                  ? document.extraction.warnings.join(" ")
                  : document.extraction.warnings}
              </p>
            ) : null}
          </Card>
        ))}
      </div>

      {selected ? (
        <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
          <Card>
            <SectionHeader title="Texto extraído" subtitle="Propuesta automática; no es un movimiento contable." />
            <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-ink-900/5 p-4 text-xs leading-relaxed text-ink-700">
              {selected.extraction.text || "Sin texto."}
            </pre>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-ink-300">
              <span>Motor: {selected.extraction.engine || "—"}</span>
              <span>SHA-256: {selected.sha256.slice(0, 12)}…</span>
            </div>
          </Card>
          <Card>
            <SectionHeader
              title="Revisar y confirmar"
              subtitle="Corrige cualquier campo. Al confirmar se registra un movimiento real con trazabilidad al documento."
            />
            <MovementForm
              key={selected.id}
              accountId={accountId}
              baseCurrency={baseCurrency}
              instruments={instruments}
              defaults={confirmDefaults}
              submitLabel="Confirmar y registrar"
              submitOverride={async (payload) => {
                await realApi.confirmDocument(selected.id, accountId, payload)
                setOpenDocument(null)
                onConfirmed()
                reload()
              }}
              onCreated={() => undefined}
            />
          </Card>
        </div>
      ) : null}
    </div>
  )
}
