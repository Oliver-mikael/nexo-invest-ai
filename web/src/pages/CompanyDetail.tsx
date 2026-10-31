import { useEffect, useMemo, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { ApiError, companiesApi, type Analysis } from "../lib/api"
import { useAsync } from "../lib/useAsync"
import { Badge, Card, ErrorNotice, Field, Notice, SectionHeader, Skeleton, Tabs, Table } from "../components/ui"
import { BarList, LineChart } from "../components/charts"
import { money, pct, price, ratio, shortDate } from "../lib/format"

type TabId = "resumen" | "valoracion" | "supuestos" | "riesgos" | "informe"

const METRIC_GROUPS: { title: string; keys: string[] }[] = [
  {
    title: "Rentabilidad",
    keys: ["revenue", "revenue_growth", "revenue_growth_fiscal", "gross_margin", "operating_margin", "net_margin", "ebitda_margin"],
  },
  {
    title: "Caja",
    keys: ["operating_cash_flow", "free_cash_flow", "fcf_conversion_ocf", "fcf_conversion_net_income", "capex_to_revenue"],
  },
  {
    title: "Balance",
    keys: ["total_debt", "cash_and_equivalents", "net_debt", "current_ratio", "quick_ratio", "interest_coverage", "net_debt_to_ebitda"],
  },
  {
    title: "Capital",
    keys: ["roic_nopat", "return_on_invested_capital", "invested_capital", "dilution_rate", "revenue_ttm"],
  },
]

function provenanceBadge(provenance: string | null) {
  if (!provenance) return <Badge tone="muted">—</Badge>
  if (provenance.includes("corroborated")) return <Badge tone="fact">corroborado</Badge>
  if (provenance.includes("validated")) return <Badge tone="fact">validado</Badge>
  if (provenance.includes("downloaded")) return <Badge tone="ai">descargado</Badge>
  return <Badge tone="muted">{provenance.replace("external_", "")}</Badge>
}

function qualityTone(label: string) {
  if (label === "validada") return "fact" as const
  if (label === "parcial") return "ai" as const
  return "warn" as const
}

function SensitivityMatrix({
  sensitivity,
  currency,
}: {
  sensitivity: Analysis["valuation"]["sensitivity"]
  currency: string
}) {
  if (!sensitivity.available) {
    return <p className="text-sm text-ink-500">Sensibilidad no disponible: {sensitivity.reason ?? "sin datos"}.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="table-base min-w-[420px] text-right">
        <thead>
          <tr>
            <th className="text-left">Descuento \ Terminal</th>
            {sensitivity.terminal_growths.map((terminal) => (
              <th key={terminal}>{pct(terminal, 2)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sensitivity.discount_rates.map((rate) => (
            <tr key={rate}>
              <td className={`font-mono text-left ${sensitivity.base?.discount_rate === rate ? "font-semibold text-moss-600" : ""}`}>
                {pct(rate, 2)}
              </td>
              {sensitivity.terminal_growths.map((terminal) => {
                const cell = sensitivity.cells.find(
                  (item) => item.discount_rate === rate && item.terminal_growth === terminal,
                )
                return (
                  <td key={`${rate}-${terminal}`} className="font-mono">
                    {cell?.per_share_value != null ? price(cell.per_share_value, currency) : "no calculable"}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function CompanyDetail() {
  const { ticker = "" } = useParams()
  const symbol = ticker.toUpperCase()
  const [params, setParams] = useSearchParams()
  const initialTab = (params.get("tab") as TabId) ?? "resumen"
  const [tab, setTab] = useState<TabId>(initialTab)
  const { data, loading, error, reload } = useAsync(() => companiesApi.analysis(symbol), [symbol])
  const [report, setReport] = useState<string | null>(null)
  const [reportBusy, setReportBusy] = useState(false)

  const baseScenario = useMemo(() => data?.valuation.scenarios.find((s) => s.name === "base") ?? null, [data])

  const [form, setForm] = useState({
    forecast_years: 5,
    growth_rate: 0.04,
    discount_rate: 0.085,
    terminal_growth: 0.025,
    fcf_adjustment: 0,
    share_price: "",
  })
  const [custom, setCustom] = useState<Awaited<ReturnType<typeof companiesApi.valuate>> | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [formBusy, setFormBusy] = useState(false)

  useEffect(() => {
    if (!baseScenario) return
    setForm((current) => ({
      ...current,
      forecast_years: baseScenario.growth_rates.length || 5,
      growth_rate: baseScenario.growth_rates[0] ?? 0.04,
      discount_rate: baseScenario.discount_rate,
      terminal_growth: baseScenario.terminal_growth,
      fcf_adjustment: baseScenario.fcf_adjustment ?? 0,
    }))
  }, [baseScenario])

  useEffect(() => {
    setTab((params.get("tab") as TabId) ?? "resumen")
  }, [params])

  const changeTab = (next: TabId) => {
    setTab(next)
    const updated = new URLSearchParams(params)
    updated.set("tab", next)
    setParams(updated, { replace: true })
  }

  const runValuation = async (event: React.FormEvent) => {
    event.preventDefault()
    setFormBusy(true)
    setFormError(null)
    try {
      const result = await companiesApi.valuate(symbol, {
        forecast_years: form.forecast_years,
        growth_rate: form.growth_rate,
        discount_rate: form.discount_rate,
        terminal_growth: form.terminal_growth,
        fcf_adjustment: form.fcf_adjustment,
        share_price: form.share_price ? Number(form.share_price) : null,
        sensitivity_steps: 1,
      })
      setCustom(result)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "No se pudo calcular la valoración.")
    } finally {
      setFormBusy(false)
    }
  }

  const loadReport = async () => {
    setReportBusy(true)
    try {
      const response = await companiesApi.engineReport(symbol)
      setReport(response.markdown)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "No se pudo generar el informe.")
    } finally {
      setReportBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton rows={2} />
        <Card>
          <Skeleton rows={6} />
        </Card>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="space-y-4">
        <ErrorNotice message={error ?? "Empresa no disponible"} onRetry={reload} />
        <Link to="/empresas" className="btn-ghost text-sm no-underline">
          Volver al explorador
        </Link>
      </div>
    )
  }

  const currency = data.identity.currency
  const metrics = new Map(data.metrics.map((metric) => [metric.key, metric]))
  const revenueSeries = (data.series.revenue ?? []).map((point) => ({
    label: point.period_end.slice(0, 4),
    value: point.value,
  }))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs uppercase tracking-[0.14em] text-ink-300">{symbol}</span>
            <Badge tone={qualityTone(data.provenance.quality_label)}>
              datos {data.provenance.quality_label}
            </Badge>
            {data.identity.cik ? <Badge tone="muted">CIK {data.identity.cik}</Badge> : null}
          </div>
          <h1 className="mt-2 font-display text-4xl leading-tight tracking-tight">{data.identity.name}</h1>
          <p className="mt-1 text-sm text-ink-500">
            Cierre {shortDate(data.identity.latest_period_end)} · moneda {currency} ·{" "}
            {data.provenance.counts.total} observaciones ({data.provenance.counts.validated} validadas,{" "}
            {data.provenance.counts.corroborated} corroboradas)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={reload}>
            Recargar
          </button>
          <Link to={`/investigacion?ticker=${symbol}`} className="btn-primary text-xs no-underline">
            Investigar con IA
          </Link>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Valor base / acción</p>
          <p className="stat-value mt-1 text-moss-600">{price(baseScenario?.per_share_value ?? null, currency)}</p>
          <p className="mt-1 text-[11px] text-ink-300">DCF con supuestos declarados</p>
        </div>
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Valor de empresa</p>
          <p className="stat-value mt-1">{money(baseScenario?.enterprise_value ?? null, currency)}</p>
          <p className="mt-1 text-[11px] text-ink-300">FCF base {money(data.valuation.base_fcf ?? null, currency)}</p>
        </div>
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Margen bruto</p>
          <p className="stat-value mt-1">{pct(metrics.get("gross_margin")?.value ?? null)}</p>
          <p className="mt-1 text-[11px] text-ink-300">Periodo {shortDate(metrics.get("gross_margin")?.period_end ?? null)}</p>
        </div>
        <div className="surface p-4">
          <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Deuda neta / EBITDA</p>
          <p className="stat-value mt-1">{ratio(metrics.get("net_debt_to_ebitda")?.value ?? null)}</p>
          <p className="mt-1 text-[11px] text-ink-300">ROIC {pct(metrics.get("roic_nopat")?.value ?? null)}</p>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={changeTab}
        tabs={[
          { id: "resumen", label: "Resumen" },
          { id: "valoracion", label: "Valoración" },
          { id: "supuestos", label: "Calculadora" },
          { id: "riesgos", label: "Riesgos" },
          { id: "informe", label: "Informe del motor" },
        ]}
      />

      {tab === "resumen" ? (
        <div className="grid gap-5 lg:grid-cols-[1.25fr_1fr]">
          <Card>
            <SectionHeader title="Ingresos anuales" subtitle="Serie de estados financieros presentados ante la SEC." />
            <LineChart points={revenueSeries} format={(value) => money(value, currency)} />
          </Card>
          <Card>
            <SectionHeader title="Calidad del dato" subtitle={data.provenance.statement} />
            <div className="space-y-3">
              <BarList
                items={[
                  { label: "Validadas", value: data.provenance.counts.validated, tone: "moss" },
                  { label: "Corroboradas", value: data.provenance.counts.corroborated, tone: "moss" },
                  { label: "Solo descargadas", value: data.provenance.counts.downloaded_only, tone: "amber" },
                  { label: "Simuladas", value: data.provenance.counts.simulated, tone: "ink" },
                ]}
                format={(value) => String(value ?? 0)}
              />
              <div className="rounded-lg border border-ink-900/10 bg-paper/60 p-3 text-xs leading-relaxed text-ink-500">
                <p>
                  Documento:{" "}
                  <a href={data.provenance.source_url} target="_blank" rel="noreferrer">
                    SEC EDGAR companyfacts
                  </a>
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-ink-300">
                  SHA-256 {data.provenance.content_sha256 || "no registrado"}
                </p>
              </div>
            </div>
          </Card>

          {METRIC_GROUPS.map((group) => (
            <Card key={group.title} className="lg:col-span-2">
              <SectionHeader title={group.title} />
              <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                {group.keys.map((key) => {
                  const metric = metrics.get(key)
                  if (!metric) return null
                  return (
                    <div key={key} className="flex items-baseline justify-between gap-3 border-b border-ink-900/5 py-2">
                      <span className="text-sm text-ink-500">{metric.label}</span>
                      <span className="text-right">
                        <span className="font-mono text-sm tabular-nums text-ink-900">
                          {metric.kind === "money"
                            ? money(metric.value, metric.currency ?? currency)
                            : metric.kind === "percent"
                              ? pct(metric.value)
                              : ratio(metric.value)}
                        </span>
                        <span className="ml-2 inline-block align-middle">{provenanceBadge(metric.provenance)}</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            </Card>
          ))}

          {data.provenance.missing_metrics.length ? (
            <Card className="lg:col-span-2">
              <SectionHeader
                title="Información ausente"
                subtitle="No se calcula ni se rellena con cero: si falta el dato, se declara."
              />
              <div className="flex flex-wrap gap-2">
                {data.provenance.missing_metrics.map((item) => (
                  <Badge key={item.key} tone="muted">
                    {item.label}
                  </Badge>
                ))}
              </div>
            </Card>
          ) : null}
        </div>
      ) : null}

      {tab === "valoracion" ? (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-3">
            {data.valuation.scenarios.map((scenario) => (
              <Card key={scenario.name}>
                <div className="flex items-center justify-between">
                  <Badge tone={scenario.name === "base" ? "fact" : "muted"}>{scenario.name}</Badge>
                  <span className="text-[11px] text-ink-300">{pct(scenario.discount_rate, 2)} descuento</span>
                </div>
                <p className="mt-3 font-mono text-2xl text-ink-900">{price(scenario.per_share_value, currency)}</p>
                <p className="mt-1 text-xs text-ink-500">{scenario.label}</p>
                <dl className="mt-3 space-y-1 text-xs text-ink-500">
                  <div className="flex justify-between">
                    <dt>Crecimiento flujo</dt>
                    <dd className="font-mono">{pct(scenario.growth_rates[0])}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Terminal</dt>
                    <dd className="font-mono">{pct(scenario.terminal_growth, 2)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Valor de empresa</dt>
                    <dd className="font-mono">{money(scenario.enterprise_value, currency)}</dd>
                  </div>
                </dl>
              </Card>
            ))}
          </div>

          <Card>
            <SectionHeader
              title="Sensibilidad del escenario base"
              subtitle="Solo cambian la tasa de descuento y el crecimiento terminal. Las combinaciones que el modelo rechaza se muestran como no calculables."
            />
            <SensitivityMatrix sensitivity={data.valuation.sensitivity} currency={currency} />
          </Card>

          <Card>
            <SectionHeader title="Proyección del escenario base" />
            <Table>
              <thead>
                <tr>
                  <th>Año</th>
                  <th className="text-right">FCF</th>
                  <th className="text-right">Factor</th>
                  <th className="text-right">Valor presente</th>
                </tr>
              </thead>
              <tbody>
                {(baseScenario?.projected_years ?? []).map((year) => (
                  <tr key={year.year}>
                    <td>{year.year}</td>
                    <td className="text-right font-mono">{money(year.free_cash_flow, currency)}</td>
                    <td className="text-right font-mono">{year.discount_factor.toFixed(4)}</td>
                    <td className="text-right font-mono">{money(year.present_value, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>

          {data.valuation.notes.length ? (
            <Notice tone="warning">
              {data.valuation.notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </Notice>
          ) : null}
        </div>
      ) : null}

      {tab === "supuestos" ? (
        <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
          <Card>
            <SectionHeader
              title="Calculadora DCF"
              subtitle="Todos los supuestos son visibles. El cálculo se ejecuta en el servidor con el FCF observado."
            />
            <form className="space-y-4" onSubmit={runValuation}>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Años de proyección">
                  <input
                    className="field"
                    type="number"
                    min={1}
                    max={15}
                    value={form.forecast_years}
                    onChange={(e) => setForm({ ...form, forecast_years: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Crecimiento del FCF">
                  <input
                    className="field"
                    type="number"
                    step="0.005"
                    min={-0.5}
                    max={0.5}
                    value={form.growth_rate}
                    onChange={(e) => setForm({ ...form, growth_rate: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Tasa de descuento">
                  <input
                    className="field"
                    type="number"
                    step="0.005"
                    min={0.01}
                    max={0.4}
                    value={form.discount_rate}
                    onChange={(e) => setForm({ ...form, discount_rate: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Crecimiento terminal">
                  <input
                    className="field"
                    type="number"
                    step="0.005"
                    min={-0.05}
                    max={0.39}
                    value={form.terminal_growth}
                    onChange={(e) => setForm({ ...form, terminal_growth: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Ajuste al FCF base" hint="-0,2 = 20 % menos">
                  <input
                    className="field"
                    type="number"
                    step="0.05"
                    min={-0.9}
                    max={1}
                    value={form.fcf_adjustment}
                    onChange={(e) => setForm({ ...form, fcf_adjustment: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Precio de mercado (opcional)" hint="Solo si lo aportas tú; no se descarga precio verificado.">
                  <input
                    className="field"
                    type="number"
                    step="0.01"
                    min={0}
                    placeholder="—"
                    value={form.share_price}
                    onChange={(e) => setForm({ ...form, share_price: e.target.value })}
                  />
                </Field>
              </div>
              {formError ? <ErrorNotice message={formError} /> : null}
              <button type="submit" className="btn-primary w-full" disabled={formBusy}>
                {formBusy ? "Calculando…" : "Calcular valoración"}
              </button>
              <p className="text-[11px] leading-relaxed text-ink-300">
                Valores decimales: 0,085 = 8,5 %. El resultado es una estimación matemática con
                supuestos declarados, no un precio objetivo.
              </p>
            </form>
          </Card>

          <div className="space-y-4">
            {custom ? (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="surface p-4">
                    <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Valor por acción</p>
                    <p className="stat-value mt-1 text-moss-600">{price(custom.result.per_share_value, custom.currency)}</p>
                  </div>
                  <div className="surface p-4">
                    <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Valor de empresa</p>
                    <p className="stat-value mt-1">{money(custom.result.enterprise_value, custom.currency)}</p>
                  </div>
                  <div className="surface p-4">
                    <p className="text-[11px] uppercase tracking-[0.09em] text-ink-300">Valor de equity</p>
                    <p className="stat-value mt-1">{money(custom.result.equity_value, custom.currency)}</p>
                  </div>
                </div>
                <Card>
                  <SectionHeader title="Sensibilidad de tus supuestos" />
                  <SensitivityMatrix
                    sensitivity={{
                      available: true,
                      discount_rates: custom.sensitivity.discount_rates,
                      terminal_growths: custom.sensitivity.terminal_growths,
                      cells: custom.sensitivity.cells,
                    }}
                    currency={custom.currency}
                  />
                  {!custom.net_debt_included ? (
                    <p className="mt-3 text-xs text-amber-600">
                      Deuda neta desconocida: el valor de patrimonio iguala al valor de empresa.
                    </p>
                  ) : null}
                </Card>
                <Notice tone="warning">{custom.warning}</Notice>
              </>
            ) : (
              <Card>
                <p className="text-sm text-ink-500">
                  Ajusta los supuestos y calcula: verás el valor por acción, el valor de empresa y
                  la tabla de sensibilidad de tu escenario.
                </p>
              </Card>
            )}
          </div>
        </div>
      ) : null}

      {tab === "riesgos" ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <SectionHeader
              title="Condiciones de invalidación"
              subtitle="Criterios objetivos, comprobables en el próximo informe."
            />
            <ul className="space-y-2 text-sm text-ink-600">
              {data.risks.invalidation_conditions.map((condition) => (
                <li key={condition} className="flex gap-2">
                  <span className="text-ink-300">—</span>
                  <span>{condition}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <SectionHeader title="Ya incumplidas" subtitle="Si alguna se cumple hoy, la tesis de calidad no se sostiene." />
            {data.risks.already_invalidated.length === 0 ? (
              <p className="text-sm text-moss-600">Ninguna condición se cumple en el periodo analizado.</p>
            ) : (
              <ul className="space-y-2 text-sm text-rust-600">
                {data.risks.already_invalidated.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="lg:col-span-2">
            <SectionHeader title="Limitaciones declaradas" />
            <p className="text-sm leading-relaxed text-ink-500">{data.limitations}</p>
            <p className="mt-3 text-xs leading-relaxed text-ink-300">
              Sin precio de mercado verificado no se calcula margen de seguridad y el sistema no
              emite recomendaciones. La valoración depende de supuestos que puedes cambiar en la
              calculadora.
            </p>
          </Card>
        </div>
      ) : null}

      {tab === "informe" ? (
        <Card>
          <SectionHeader
            title="Informe reproducible del motor"
            subtitle="Markdown generado con la procedencia de cada cifra. Se guarda en el historial al generarlo."
            action={
              <button type="button" className="btn-dark text-xs" onClick={loadReport} disabled={reportBusy}>
                {reportBusy ? "Generando…" : report ? "Regenerar" : "Generar informe"}
              </button>
            }
          />
          {report ? (
            <>
              <div className="mb-3 flex flex-wrap gap-2">
                <Link to="/informes" className="btn-ghost text-xs no-underline">
                  Ver historial
                </Link>
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={() => {
                    const blob = new Blob([report], { type: "text/markdown;charset=utf-8" })
                    const url = URL.createObjectURL(blob)
                    const anchor = document.createElement("a")
                    anchor.href = url
                    anchor.download = `nexo-${symbol.toLowerCase()}-motor.md`
                    anchor.click()
                    URL.revokeObjectURL(url)
                  }}
                >
                  Descargar Markdown
                </button>
              </div>
              <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-ink-900/10 bg-white p-4 font-mono text-xs leading-relaxed text-ink-700">
                {report}
              </pre>
            </>
          ) : (
            <p className="text-sm text-ink-500">
              El informe incluye identificación, calidad del dato, hechos con fuente, datos sin
              validar, ausencias, indicadores, escenarios, sensibilidad, riesgos y trazabilidad.
            </p>
          )}
        </Card>
      ) : null}
    </div>
  )
}
