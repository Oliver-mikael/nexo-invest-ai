export function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const abs = Math.abs(value)
  const format = (v: number, suffix = "") => {
    const digits = abs >= 100 ? 0 : abs >= 1 ? 2 : 4
    return `${v.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits })}${suffix}`
  }
  if (abs >= 1e12) return `${format(value / 1e12)} B ${currency}`
  if (abs >= 1e9) return `${format(value / 1e9)} MM ${currency}`
  if (abs >= 1e6) return `${format(value / 1e6)} M ${currency}`
  return `${format(value)} ${currency}`
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} B`
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)} MM`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)} M`
  return value.toLocaleString("es-ES", { maximumFractionDigits: 2 })
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)} %`
}

export function ratio(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${value.toFixed(digits)}x`
}

export function price(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" })
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
}

export function relative(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value).getTime()
  if (Number.isNaN(date)) return "—"
  const seconds = Math.round((Date.now() - date) / 1000)
  if (seconds < 60) return "hace un momento"
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)} h`
  if (seconds < 2592000) return `hace ${Math.floor(seconds / 86400)} d`
  return shortDate(value)
}

export function metricValue(metric: { kind: string; value: number | null; currency: string | null }, currency: string): string {
  if (metric.kind === "money") return money(metric.value, metric.currency ?? currency)
  if (metric.kind === "percent") return pct(metric.value)
  return ratio(metric.value)
}

export function statusLabel(status: string): { text: string; tone: "fact" | "ai" | "warn" | "muted" } {
  switch (status) {
    case "completed":
      return { text: "Completada", tone: "fact" }
    case "running":
      return { text: "En ejecución", tone: "ai" }
    case "queued":
      return { text: "En cola", tone: "muted" }
    case "failed":
      return { text: "Fallida", tone: "warn" }
    case "cancelled":
      return { text: "Cancelada", tone: "muted" }
    default:
      return { text: status, tone: "muted" }
  }
}
