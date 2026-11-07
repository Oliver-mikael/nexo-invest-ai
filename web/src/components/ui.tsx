import type { ReactNode } from "react"

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`surface p-5 ${className}`}>{children}</section>
}

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="font-display text-2xl leading-tight text-ink-900">{title}</h2>
        {subtitle ? <p className="mt-1 max-w-2xl text-sm text-ink-500">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: "default" | "good" | "warn"
}) {
  const color =
    tone === "good" ? "text-moss-600" : tone === "warn" ? "text-amber-600" : "text-ink-900"
  return (
    <div className="surface p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-500">{label}</p>
      <p className={`stat-value mt-2 ${color}`}>{value}</p>
      {hint ? <p className="mt-1 text-xs leading-relaxed text-ink-500">{hint}</p> : null}
    </div>
  )
}

const TONES: Record<string, string> = {
  fact: "chip-fact",
  ai: "chip-ai",
  warn: "chip-warn",
  muted: "chip-muted",
}

export function Badge({ tone = "muted", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={TONES[tone] ?? TONES.muted}>{children}</span>
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-ink-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-900/15 border-t-moss-600" />
      {label ?? "Cargando…"}
    </div>
  )
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton h-4" style={{ width: `${90 - index * 12}%` }} />
      ))}
    </div>
  )
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-rust-600/25 bg-rust-100/70 p-4 text-sm text-rust-600">
      <p className="font-medium">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="mt-2 text-xs font-semibold underline">
          Reintentar
        </button>
      ) : null}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="rounded-xl border border-dashed border-ink-900/15 bg-white/50 p-8 text-center">
      <p className="font-display text-xl text-ink-900">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[]
  value: T
  onChange: (id: T) => void
}) {
  return (
    <div className="flex gap-1 overflow-x-auto rounded-lg border border-ink-900/10 bg-white/70 p-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            value === tab.id ? "bg-ink-900 text-paper" : "text-ink-500 hover:text-ink-900"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] leading-relaxed text-ink-300">{hint}</span> : null}
    </label>
  )
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="table-base min-w-[560px]">{children}</table>
    </div>
  )
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "error" | "success"
  children: ReactNode
}) {
  const styles = {
    info: "border-ink-900/10 bg-white/70 text-ink-600",
    warning: "border-amber-600/25 bg-amber-100/70 text-amber-600",
    error: "border-rust-600/25 bg-rust-100/70 text-rust-600",
    success: "border-moss-600/25 bg-moss-100/70 text-moss-600",
  }[tone]
  return <div className={`rounded-lg border px-4 py-3 text-sm leading-relaxed ${styles}`}>{children}</div>
}

export function Progress({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(1, value))
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-900/10">
      <div className="h-full rounded-full bg-moss-500 transition-all" style={{ width: `${clamped * 100}%` }} />
    </div>
  )
}
