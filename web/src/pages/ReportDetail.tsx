import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { reportsApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Notice, SectionHeader, Table } from "../components/ui"
import { downloadReport, openPrintable } from "../lib/download"
import { dateTime, money } from "../lib/format"

function basisTone(basis: string) {
  if (basis === "fact" || basis === "source") return "fact" as const
  if (basis === "ai") return "ai" as const
  if (basis === "unavailable") return "muted" as const
  return "warn" as const
}

export function ReportDetail() {
  const { id = "" } = useParams()
  const reportId = Number(id)
  const navigate = useNavigate()
  const { data, loading, error, reload } = useAsync(() => reportsApi.get(reportId), [reportId])
  const [actionError, setActionError] = useState<string | null>(null)

  if (loading) return <p className="text-sm text-ink-300">Cargando informe…</p>
  if (error || !data)
    return (
      <div className="space-y-3">
        <ErrorNotice message={error ?? "Informe no disponible"} onRetry={reload} />
        <Link to="/informes" className="btn-ghost text-sm no-underline">
          Volver
        </Link>
      </div>
    )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs uppercase tracking-[0.14em] text-ink-300">{data.ticker}</span>
            <Badge tone={data.kind === "research" ? "ai" : "muted"}>{data.kind}</Badge>
            {data.base_per_share != null ? (
              <Badge tone="fact">valor base {money(data.base_per_share, data.currency ?? "USD")}</Badge>
            ) : null}
          </div>
          <h1 className="mt-2 font-display text-4xl leading-tight tracking-tight">{data.title}</h1>
          <p className="mt-1 text-sm text-ink-500">
            {dateTime(data.created_at)} · calidad del dato: {data.provenance?.quality_label ?? "—"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/empresas/${data.ticker}`} className="btn-ghost text-xs no-underline">
            Ficha
          </Link>
          <button type="button" className="btn-ghost text-xs" onClick={() => openPrintable(data.id)}>
            Imprimir / PDF
          </button>
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={async () => {
              try {
                await downloadReport(data.id, "md")
              } catch (err) {
                setActionError(err instanceof Error ? err.message : "Error al exportar")
              }
            }}
          >
            Markdown
          </button>
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={async () => {
              try {
                await downloadReport(data.id, "csv")
              } catch (err) {
                setActionError(err instanceof Error ? err.message : "Error al exportar")
              }
            }}
          >
            CSV
          </button>
          <button
            type="button"
            className="btn-danger text-xs"
            onClick={async () => {
              if (!window.confirm("¿Eliminar este informe del historial?")) return
              await reportsApi.remove(data.id)
              navigate("/informes")
            }}
          >
            Eliminar
          </button>
        </div>
      </div>

      {actionError ? <ErrorNotice message={actionError} /> : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Auditoría de cifras</p>
          <p className={`stat-value mt-1 ${data.audit.unsupported_count ? "text-amber-600" : "text-moss-600"}`}>
            {data.audit.unsupported_count}
          </p>
          <p className="mt-1 text-xs text-ink-300">sin respaldo en el expediente</p>
        </div>
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Citas a evidencia</p>
          <p className="stat-value mt-1">{data.audit.cited_evidence?.length ?? 0}</p>
          <p className="mt-1 text-xs text-ink-300">
            {data.audit.unknown_citations?.length ? `${data.audit.unknown_citations.length} inválidas` : "todas válidas"}
          </p>
        </div>
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Coste de IA</p>
          <p className="stat-value mt-1">
            {data.roles.reduce((total, role) => total + (role.usage?.cost_usd ?? 0), 0).toFixed(4)} USD
          </p>
          <p className="mt-1 text-xs text-ink-300">{data.roles.length} rol(es)</p>
        </div>
      </div>

      {data.audit.unsupported_numbers?.length ? (
        <Notice tone="warning">
          <p className="font-medium">Cifras marcadas por el auditor:</p>
          <ul className="mt-1 space-y-1 text-xs">
            {data.audit.unsupported_numbers.slice(0, 8).map((item, index) => (
              <li key={`${item.raw}-${index}`}>
                [{item.role}] {item.raw} — «{item.context.slice(0, 120)}»
              </li>
            ))}
          </ul>
        </Notice>
      ) : null}

      <div className="space-y-5">
        {data.sections.map((section) => (
          <Card key={section.id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-2xl text-ink-900">{section.title}</h2>
              <Badge tone={basisTone(section.basis)}>{section.basis_label}</Badge>
            </div>
            {section.paragraphs.map((paragraph, index) => (
              <p key={index} className="mb-3 whitespace-pre-line text-sm leading-relaxed text-ink-600">
                {paragraph}
              </p>
            ))}
            {section.bullets.length ? (
              <ul className="mb-3 space-y-1.5 text-sm leading-relaxed text-ink-600">
                {section.bullets.map((bullet, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="text-ink-300">—</span>
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {section.table ? (
              <div className="overflow-x-auto">
                {section.table.caption ? (
                  <p className="mb-2 text-xs text-ink-300">{section.table.caption}</p>
                ) : null}
                <table className="table-base min-w-[480px] text-right">
                  <thead>
                    <tr>
                      {section.table.columns.map((column) => (
                        <th key={column} className="first:text-left">
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {section.table.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} className={`font-mono text-xs ${cellIndex === 0 ? "text-left" : ""}`}>
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Card>
        ))}
      </div>

      <Card>
        <SectionHeader title="Roles ejecutados" subtitle="Modelo, estado y consumo real por rol." />
        {data.roles.length === 0 ? (
          <p className="text-sm text-ink-500">
            Informe generado por el motor, sin intervención de modelos.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Rol</th>
                <th>Estado</th>
                <th>Modelo</th>
                <th className="text-right">Tokens</th>
                <th className="text-right">Coste</th>
              </tr>
            </thead>
            <tbody>
              {data.roles.map((role) => (
                <tr key={role.role}>
                  <td>{role.label}</td>
                  <td>
                    <Badge tone={role.status === "completed" ? "fact" : "warn"}>{role.status}</Badge>
                  </td>
                  <td className="font-mono text-xs text-ink-500">{role.model}</td>
                  <td className="text-right font-mono text-xs">
                    {role.usage.tokens_in}/{role.usage.tokens_out}
                  </td>
                  <td className="text-right font-mono text-xs">{role.usage.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p className="mt-4 text-xs leading-relaxed text-ink-300">
          Las cifras provienen del motor y de la SEC. Las interpretaciones de IA están etiquetadas en
          cada sección. Este documento no es asesoramiento financiero.
        </p>
      </Card>
    </div>
  )
}
