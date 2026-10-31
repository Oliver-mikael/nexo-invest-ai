import { getToken } from "./api"

/** Descarga una exportación autenticada (el enlace directo no puede llevar la cabecera). */
export async function downloadReport(id: number, format: "md" | "csv" | "html") {
  const token = getToken()
  const response = await fetch(`/api/v1/reports/${id}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new Error(`No se pudo exportar (HTTP ${response.status})`)
  const blob = await response.blob()
  const disposition = response.headers.get("content-disposition") ?? ""
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match?.[1] ?? `nexo-informe-${id}.${format}`
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function openPrintable(id: number) {
  const token = getToken()
  void fetch(`/api/v1/reports/${id}/export?format=html`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then((response) => response.text())
    .then((html) => {
      const win = window.open("", "_blank")
      if (!win) return
      win.document.write(html)
      win.document.close()
      win.focus()
      setTimeout(() => win.print(), 400)
    })
}
