import { useState } from "react"
import { Link } from "react-router-dom"
import { reportsApi } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, SectionHeader, Table, Tabs } from "../components/ui"
import { downloadReport, openPrintable } from "../lib/download"
import { money, shortDate } from "../lib/format"

type Filter = "all" | "research" | "engine"

export function Reports() {
  const [filter, setFilter] = useState<Filter>("all")
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const query = filter === "all" ? "" : `?kind=${filter}`
  const { data, loading, error: loadError, reload } = useAsync(() => reportsApi.list(query), [query])

  const exportAs = async (id: number, format: "md" | "csv" | "html") => {
    setBusy(id)
    setError(null)
    try {
      if (format === "html") openPrintable(id)
      else await downloadReport(id, format)
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo exportar")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Biblioteca</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Informes</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Cada informe conserva sus secciones, la auditoría de cifras y los roles que intervinieron.
          Exporta a Markdown, CSV o HTML imprimible (PDF desde el navegador).
        </p>
      </div>

      <Tabs
        value={filter}
        onChange={setFilter}
        tabs={[
          { id: "all", label: "Todos" },
          { id: "research", label: "Investigación" },
          { id: "engine", label: "Motor" },
        ]}
      />

      {loadError ? <ErrorNotice message={loadError} onRetry={reload} /> : null}
      {error ? <ErrorNotice message={error} /> : null}

      <Card>
        <SectionHeader
          title={`${data?.total ?? 0} informe(s)`}
          subtitle="Los informes se guardan en tu cuenta y no se comparten entre usuarios."
        />
        {loading && !data ? (
          <p className="text-sm text-ink-300">Cargando…</p>
        ) : (data?.items.length ?? 0) === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-900/15 p-6 text-center text-sm text-ink-500">
            Sin informes. Genera uno desde la ficha de una empresa o lanza una investigación.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Informe</th>
                <th>Tipo</th>
                <th className="text-right">Valor base</th>
                <th className="text-right">Fecha</th>
                <th className="text-right">Exportar</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((report) => (
                <tr key={report.id}>
                  <td>
                    <Link to={`/informes/${report.id}`} className="font-medium no-underline">
                      {report.title}
                    </Link>
                    <span className="ml-2 font-mono text-[11px] text-ink-300">{report.ticker}</span>
                  </td>
                  <td>
                    <Badge tone={report.kind === "research" ? "ai" : "muted"}>
                      {report.kind === "research" ? "investigación" : "motor"}
                    </Badge>
                  </td>
                  <td className="text-right font-mono text-xs">
                    {report.base_per_share != null ? money(report.base_per_share) : "—"}
                  </td>
                  <td className="text-right text-xs text-ink-300">{shortDate(report.created_at)}</td>
                  <td className="text-right">
                    <div className="flex justify-end gap-1">
                      {(["md", "csv", "html"] as const).map((format) => (
                        <button
                          key={format}
                          type="button"
                          className="rounded border border-ink-900/10 px-1.5 py-0.5 text-[10px] uppercase text-ink-500 hover:border-moss-600/40 hover:text-moss-600"
                          onClick={() => exportAs(report.id, format)}
                          disabled={busy === report.id}
                        >
                          {format}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  )
}
