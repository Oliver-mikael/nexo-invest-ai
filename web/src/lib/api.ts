const BASE = "/api/v1"
const TOKEN_KEY = "nexo.token"

export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* almacenamiento no disponible: la sesión dura lo que la pestaña */
  }
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE"
  body?: unknown
  signal?: AbortSignal
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { Accept: "application/json" }
  if (options.body !== undefined) headers["Content-Type"] = "application/json"
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error
    throw new ApiError(0, "offline", "Sin conexión: esta acción necesita red.")
  }

  if (response.status === 401) {
    setToken(null)
  }

  if (!response.ok) {
    let code = "http_error"
    let message = `Error ${response.status}`
    let details: Record<string, unknown> = {}
    try {
      const payload = await response.json()
      if (payload?.error) {
        code = payload.error.code ?? code
        message = payload.error.message ?? message
        details = payload.error.details ?? {}
      }
    } catch {
      /* respuesta sin JSON */
    }
    if (response.status === 422 && Array.isArray((details as { fields?: unknown }).fields)) {
      const fields = (details as { fields: { field: string; message: string }[] }).fields
      if (fields.length) message = fields.map((f) => `${f.field}: ${f.message}`).join(" · ")
    }
    throw new ApiError(response.status, code, message, details)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// -- tipos compartidos ---------------------------------------------------------

export type User = {
  id: number
  email: string
  display_name: string
  role: string
  created_at: string
}

export type AuthResponse = {
  access_token: string
  token_type: string
  expires_at: string
  user: User
}

export type Metric = {
  key: string
  label: string
  kind: "money" | "percent" | "ratio"
  value: number | null
  currency: string | null
  period_end: string | null
  provenance: string | null
  source_url: string | null
  unit: string
}

export type Scenario = {
  name: string
  label: string
  growth_rates: number[]
  terminal_growth: number
  discount_rate: number
  fcf_adjustment: number | null
  per_share_value: number | null
  enterprise_value: number | null
  equity_value: number | null
  terminal_value_pv: number | null
  projected_years: { year: string; free_cash_flow: number; discount_factor: number; present_value: number }[]
  notes: Record<string, string>
  share_price: number | null
  upside: number | null
}

export type Sensitivity = {
  available: boolean
  reason?: string
  discount_rates: number[]
  terminal_growths: number[]
  cells: { discount_rate: number; terminal_growth: number; per_share_value: number | null }[]
  base?: { discount_rate: number; terminal_growth: number; per_share_value: number | null }
}

export type Analysis = {
  identity: {
    ticker: string
    name: string
    cik: number | null
    currency: string
    latest_period_end: string
    fiscal_close_month: number
    generated_at: string
    shares_outstanding: number | null
  }
  provenance: {
    source_url: string
    content_sha256: string
    quality_label: string
    counts: {
      total: number
      validated: number
      corroborated: number
      downloaded_only: number
      simulated: number
    }
    share_validated: number
    statement: string
    missing_metrics: { key: string; label: string }[]
  }
  metrics: Metric[]
  series: Record<string, { period_end: string; value: number; provenance: string }[]>
  valuation: {
    scenarios: Scenario[]
    sensitivity: Sensitivity
    notes: string[]
    base_fcf: number | null
    fcf_estimated: boolean
  }
  risks: { invalidation_conditions: string[]; already_invalidated: string[] }
  limitations: string
}

export type PortfolioSummary = {
  id?: number
  name: string
  currency: string
  starting_cash: number
  cash: number
  invested_at_cost: number
  market_value: number
  total_value: number
  total_return: number | null
  realized_pnl: number
  unrealized_pnl: number
  positions: {
    symbol: string
    quantity: number
    avg_cost: number
    price: number | null
    priced: boolean
    market_value: number
    unrealized: number | null
    weight: number | null
    thesis: string
  }[]
  benchmark: { symbol: string; return: number | null }
  prices_source: string
  priced_positions: number
  total_positions: number
  warning: string
}

export type ReportSection = {
  id: string
  title: string
  basis: string
  basis_label: string
  paragraphs: string[]
  bullets: string[]
  table: { columns: string[]; rows: string[][]; caption?: string } | null
}

export type ReportDetail = {
  id: number
  ticker: string
  title: string
  kind: string
  created_at: string
  markdown: string
  sections: ReportSection[]
  audit: {
    unsupported_numbers: { role: string; raw: string; context: string }[]
    unsupported_count: number
    unknown_citations: string[]
    cited_evidence: string[]
    verdict: string
  }
  roles: { role: string; label: string; status: string; model: string; usage: { cost_usd: number; tokens_in: number; tokens_out: number } }[]
  provenance: Analysis["provenance"]
  metrics: Metric[]
  scenarios: Scenario[]
  base_per_share: number | null
  currency: string | null
}

export type Job = {
  id: number
  ticker: string
  status: "queued" | "running" | "completed" | "failed" | "cancelled"
  stage: string
  profile: string
  budget_usd: number
  cost_usd: number
  tokens_in: number
  tokens_out: number
  attempts: number
  cancel_requested: boolean
  error: string
  report_id: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  steps: { role: string; status: string; provider: string; model: string; tokens_in: number; tokens_out: number; cost_usd: number; error: string }[]
}

export type Dashboard = {
  system: {
    version: string
    environment: string
    ai_available: boolean
    engine_ready: boolean
    providers: { name: string; kind: string; configured: boolean; models: string[] }[]
    jobs_running: number
  }
  usage: { period: string; used_usd: number; limit_usd: number; remaining_usd: number; jobs: number; tokens_in: number; tokens_out: number }
  jobs: { id: number; ticker: string; status: string; stage: string; profile: string; created_at: string; report_id: number | null }[]
  reports: { id: number; ticker: string; title: string; kind: string; created_at: string }[]
  companies: { ticker: string; name: string; cik: number | null }[]
  portfolios: { id: number; name: string; cash: number; currency: string }[]
  alerts: { level: "info" | "warning" | "error"; message: string }[]
}

// -- endpoints -----------------------------------------------------------------

export const authApi = {
  login: (email: string, password: string) =>
    api<AuthResponse>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, display_name: string) =>
    api<AuthResponse>("/auth/register", { method: "POST", body: { email, password, display_name } }),
  me: () => api<User>("/auth/me"),
  logout: () => api<{ ok: boolean }>("/auth/logout", { method: "POST" }),
}

export const companiesApi = {
  search: (q: string) =>
    api<{ items: { ticker: string; name: string; cik: number | null; sector: string; industry: string }[]; total: number }>(
      `/companies?q=${encodeURIComponent(q)}&limit=24`,
    ),
  get: (ticker: string) => api<{ ticker: string; name: string; cik: number | null }>(`/companies/${ticker}`),
  analysis: (ticker: string, refresh = false) =>
    api<Analysis>(`/companies/${ticker}/analysis?refresh=${refresh}`),
  refresh: (ticker: string) => api<{ ok: boolean }>(`/companies/${ticker}/refresh`, { method: "POST" }),
  valuate: (ticker: string, body: Record<string, unknown>) =>
    api<{
      per_share_value?: number
      result: { per_share_value: number | null; enterprise_value: number | null; equity_value: number | null; upside: number | null }
      sensitivity: { discount_rates: number[]; terminal_growths: number[]; cells: { discount_rate: number; terminal_growth: number; per_share_value: number | null }[] }
      assumptions: Record<string, number | null>
      base_fcf: number | null
      currency: string
      net_debt_included: boolean
      notes: Record<string, string>
      warning: string
    }>(`/companies/${ticker}/valuation`, { method: "POST", body }),
  engineReport: (ticker: string) =>
    api<{ markdown: string; saved_report_id: number | null }>(`/companies/${ticker}/report?save=true`),
}

export const researchApi = {
  plan: (profile: string) =>
    api<{
      ai_available: boolean
      plan: { profile: string; roles: { role: string; label: string; model: string }[]; estimated_max_cost_usd?: number }
      usage: Dashboard["usage"]
      default_budget_usd: number
      max_budget_usd: number
    }>(`/research/plan?profile=${profile}`),
  create: (ticker: string, profile: string, budget?: number) =>
    api<{ id: number; ticker: string; status: string; profile: string; note?: string }>("/research", {
      method: "POST",
      body: { ticker, profile, budget_usd: budget ?? null },
    }),
  list: () => api<{ items: Job[]; total: number }>("/research?limit=30"),
  get: (id: number) => api<Job>(`/research/${id}`),
  cancel: (id: number) => api<{ status: string; changed: boolean }>(`/research/${id}/cancel`, { method: "POST" }),
}

export const reportsApi = {
  list: (params = "") => api<{ items: { id: number; ticker: string; title: string; kind: string; created_at: string; base_per_share: number | null }[]; total: number }>(`/reports${params}`),
  get: (id: number) => api<ReportDetail>(`/reports/${id}`),
  remove: (id: number) => api<{ ok: boolean }>(`/reports/${id}`, { method: "DELETE" }),
  exportUrl: (id: number, format: "md" | "csv" | "html") => `${BASE}/reports/${id}/export?format=${format}`,
}

export const portfolioApi = {
  list: () => api<{ items: { id: number; name: string; currency: string; total_value: number; total_return: number | null; positions: number }[]; total: number }>("/portfolios"),
  create: (body: { name: string; starting_cash: number; benchmark: string }) =>
    api<{ id: number }>("/portfolios", { method: "POST", body }),
  get: (id: number) => api<PortfolioSummary>(`/portfolios/${id}`),
  trade: (id: number, body: Record<string, unknown>) =>
    api<{ trade: { id: number; symbol: string }; portfolio: { cash: number } }>(`/portfolios/${id}/trades`, {
      method: "POST",
      body,
    }),
  trades: (id: number) => api<{ items: { id: number; symbol: string; side: string; quantity: number; price: number; fee: number; executed_at: string; note: string }[] }>(`/portfolios/${id}/trades`),
}

export const systemApi = {
  dashboard: () => api<Dashboard>("/dashboard"),
  health: () => api<{ status: string; version: string; database: string; ai_enabled: boolean }>("/health"),
  settings: () =>
    api<{
      ai_profile: string
      monthly_budget_usd: number
      default_forecast_years: number
      preferred_provider: string
      benchmark: string
      usage: Dashboard["usage"]
      default_job_budget_usd: number
      max_job_budget_usd: number
      ai_available: boolean
      providers: { name: string; kind: string; configured: boolean; models: string[] }[]
    }>("/settings"),
  updateSettings: (body: Record<string, unknown>) => api<{ ok: boolean }>("/settings", { method: "PATCH", body }),
}
