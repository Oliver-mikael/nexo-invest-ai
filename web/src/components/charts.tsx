import { useId, useMemo } from "react"

type Point = { label: string; value: number }

/**
 * Gráfico de línea en SVG, sin dependencias.
 * El componente es puramente de presentación: todos los valores llegan calculados
 * desde el backend.
 */
export function LineChart({
  points,
  height = 180,
  format,
  accent = "#0b6b53",
}: {
  points: Point[]
  height?: number
  format: (value: number) => string
  accent?: string
}) {
  const gradientId = useId()
  const geometry = useMemo(() => {
    if (points.length === 0) return null
    const width = 640
    const padding = { top: 14, right: 12, bottom: 24, left: 12 }
    const values = points.map((p) => p.value)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || Math.abs(max) || 1
    const innerW = width - padding.left - padding.right
    const innerH = height - padding.top - padding.bottom
    const step = points.length > 1 ? innerW / (points.length - 1) : 0
    const coords = points.map((point, index) => ({
      x: padding.left + step * index,
      y: padding.top + innerH - ((point.value - min) / span) * innerH,
      ...point,
    }))
    const line = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(" ")
    const area = `${line} L${coords[coords.length - 1].x.toFixed(2)},${(height - padding.bottom).toFixed(2)} L${coords[0].x.toFixed(2)},${(height - padding.bottom).toFixed(2)} Z`
    return { width, coords, line, area }
  }, [points, height])

  if (!geometry) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-ink-900/15 text-sm text-ink-300">
        Sin serie histórica disponible
      </div>
    )
  }

  const last = geometry.coords[geometry.coords.length - 1]
  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${geometry.width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label="Serie histórica"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accent} stopOpacity="0.18" />
            <stop offset="100%" stopColor={accent} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
          <line
            key={fraction}
            x1="0"
            x2={geometry.width}
            y1={14 + (height - 38) * fraction}
            y2={14 + (height - 38) * fraction}
            stroke="rgba(13,18,21,0.06)"
            strokeWidth="1"
          />
        ))}
        <path d={geometry.area} fill={`url(#${gradientId})`} />
        <path d={geometry.line} fill="none" stroke={accent} strokeWidth="2" strokeLinejoin="round" />
        <circle cx={last.x} cy={last.y} r="4" fill={accent} stroke="#fff" strokeWidth="2" />
        <text x={last.x} y={last.y - 10} textAnchor="end" fontSize="11" fill="#4b5c66" fontFamily="monospace">
          {format(last.value)}
        </text>
        {geometry.coords.map((point, index) => (
          <text
            key={`${point.label}-${index}`}
            x={point.x}
            y={height - 6}
            textAnchor={index === 0 ? "start" : index === geometry.coords.length - 1 ? "end" : "middle"}
            fontSize="10"
            fill="#8a9aa3"
          >
            {point.label}
          </text>
        ))}
      </svg>
    </div>
  )
}

export function BarList({
  items,
  format,
}: {
  items: { label: string; value: number | null; tone?: "moss" | "amber" | "ink" }[]
  format: (value: number | null) => string
}) {
  const max = Math.max(...items.map((item) => Math.abs(item.value ?? 0)), 1)
  return (
    <div className="space-y-3">
      {items.map((item) => {
        const width = item.value === null ? 0 : (Math.abs(item.value) / max) * 100
        const color =
          item.tone === "amber" ? "bg-amber-500" : item.tone === "ink" ? "bg-ink-700" : "bg-moss-500"
        return (
          <div key={item.label}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-ink-600">{item.label}</span>
              <span className="font-mono tabular-nums text-ink-900">{format(item.value)}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-900/5">
              <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
