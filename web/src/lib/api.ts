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

async function parseError(response: Response): Promise<ApiError> {
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
  return new ApiError(response.status, code, message, details)
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

  if (!response.ok) throw await parseError(response)

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiUpload<T>(path: string, body: FormData): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { Accept: "application/json" }
  if (token) headers.Authorization = `Bearer ${token}`
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { method: "POST", headers, body })
  } catch {
    throw new ApiError(0, "offline", "Sin conexión: esta acción necesita red.")
  }
  if (response.status === 401) setToken(null)
  if (!response.ok) throw await parseError(response)
  return (await response.json()) as T
}

export async function apiDownload(path: string): Promise<Blob> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${BASE}${path}`, { headers })
  if (!response.ok) throw await parseError(response)
  return response.blob()
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

// -- cartera real multimercado -------------------------------------------------

export type Market = {
  code: string
  name: string
  country_code: string
  currency: string
  timezone: string
  status: string
}

export type Instrument = {
  uid: string
  symbol: string
  name: string
  market: string
  market_name: string
  country_code: string
  currency: string
  instrument_type: string
  isin: string | null
  cik: number | null
  status: string
}

export type RealAccount = {
  id: number
  name: string
  broker_name: string
  broker_country: string
  account_type: string
  base_currency: string
  cost_method: "fifo" | "average"
  commission_scheme: Record<string, unknown>
  allow_negative_cash: boolean
  allow_short: boolean
  status: string
  positions: number
  created_at: string | null
}

export type RealPosition = {
  instrument_uid: string
  symbol: string
  name: string
  market: string
  country_code: string
  instrument_type: string
  currency: string
  quantity: string
  cost_local: string
  cost_base: string
  price: string | null
  quote_as_of: string | null
  quote_source: string
  market_value_local: string | null
  market_value_base: string | null
  unrealized_base: string | null
  price_effect_base: string | null
  fx_effect_base: string | null
  realized_base: string
  dividends_base: string
  weight: string | null
}

export type RealSummary = {
  as_of: string
  base_currency: string
  cost_method: string
  cash: Record<string, string>
  cash_base: string
  cash_complete: boolean
  market_value_base: string
  total_value_base: string | null
  net_contributions_base: string
  net_gain_base: string | null
  net_return_pct: string | null
  realized_base: string
  unrealized_base: string
  dividends_base: string
  other_fees_base: string
  other_taxes_base: string
  complete: boolean
  missing_prices: string[]
  missing_fx: string[]
  warnings: string[]
  positions: RealPosition[]
  account: {
    id: number
    name: string
    broker_name: string
    broker_country: string
    account_type: string
    base_currency: string
    cost_method: string
    status: string
  }
  movements: number
  xirr_pct: string | null
  xirr_available: boolean
  twr_pct: string | null
  twr_available: boolean
  twr_reason: string
  data_errors: string[]
}

export type RealMovement = {
  id: number
  movement_type: string
  movement_date: string
  settlement_date: string | null
  instrument_uid: string | null
  symbol: string | null
  currency: string
  quantity: string
  price: string
  amount: string
  fee: string
  tax: string
  fx_rate: string
  fx_date: string | null
  fx_source: string
  source: string
  validation_status: string
  transfer_group: string | null
  transfer_cost_basis: string | null
  document_id: number | null
  import_batch_id: number | null
  notes: string
  created_at: string | null
}

export type RealOverviewGroup = {
  currency: string
  accounts: number
  market_value: string
  cash: string
  total_value: string | null
  net_contributions: string
  net_gain: string | null
  net_return_pct: string | null
  realized: string
  unrealized: string
  dividends: string
  other_fees: string
  other_taxes: string
  xirr_pct: string | null
  complete: boolean
  by_market: Record<string, string>
  by_country: Record<string, string>
  by_type: Record<string, string>
  by_currency: Record<string, string>
}

export type RealOverview = {
  as_of: string
  accounts: {
    id: number
    name: string
    broker_name: string
    broker_country: string
    account_type: string
    base_currency: string
    cost_method: string
    status: string
    total_value_base: string | null
    net_contributions_base: string
    net_gain_base: string | null
    net_return_pct: string | null
    xirr_pct: string | null
    realized_base: string
    unrealized_base: string
    dividends_base: string
    complete: boolean
    positions: number
  }[]
  groups: RealOverviewGroup[]
  currencies: string[]
  note: string
}

export type ImportPreparedRow = {
  row: number
  raw: Record<string, string>
  payload: Record<string, string | null> | null
  errors: string[]
  duplicate: boolean
  duplicate_reason: string
}

export type ImportPreview = {
  id: number
  account_id: number
  filename: string
  status: string
  mapping: Record<string, string>
  total_rows: number
  valid_rows: number
  duplicate_rows: number
  error_rows: number
  ready_to_confirm: boolean
  rows: ImportPreparedRow[]
  rows_returned: number
  headers: string[]
  note: string
}

export type DocumentRecord = {
  id: number
  account_id: number | null
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  status: string
  extraction: {
    text?: string
    engine?: string
    fields?: Record<string, string>
    warnings?: string[] | string
    review_required?: boolean
    note?: string
  }
  created_at: string | null
  updated_at: string | null
}

export const marketsApi = {
  list: () => api<Market[]>("/markets"),
  instruments: (q = "", market = "") =>
    api<{ items: Instrument[]; total: number }>(
      `/instruments?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&limit=60`,
    ),
  createInstrument: (body: {
    symbol: string
    name: string
    market_code: string
    currency: string
    instrument_type: string
    country_code?: string
  }) => api<Instrument>("/instruments", { method: "POST", body }),
  quote: (uid: string, body: { price: string; as_of: string; source: string; quality: string }) =>
    api<{ price: string }>(`/instruments/${uid}/quotes`, { method: "POST", body }),
  fx: (body: {
    base_currency: string
    quote_currency: string
    rate: string
    as_of: string
    source: string
    quality: string
  }) => api<{ rate: string }>("/fx-rates", { method: "POST", body }),
}

export const realApi = {
  overview: (asOf?: string) =>
    api<RealOverview>(`/real/overview${asOf ? `?as_of=${asOf}` : ""}`),
  accounts: () => api<{ items: RealAccount[]; total: number }>("/real/accounts"),
  account: (id: number) => api<RealAccount>(`/real/accounts/${id}`),
  createAccount: (body: Record<string, unknown>) =>
    api<RealAccount>("/real/accounts", { method: "POST", body }),
  updateAccount: (id: number, body: Record<string, unknown>) =>
    api<RealAccount>(`/real/accounts/${id}`, { method: "PATCH", body }),
  deleteAccount: (id: number) => api<{ ok: boolean }>(`/real/accounts/${id}`, { method: "DELETE" }),
  summary: (id: number, asOf?: string, twr = true) =>
    api<RealSummary>(
      `/real/accounts/${id}/summary?twr=${twr}${asOf ? `&as_of=${asOf}` : ""}`,
    ),
  movements: (id: number, limit = 200) =>
    api<{ items: RealMovement[]; total: number }>(
      `/real/accounts/${id}/movements?limit=${limit}`,
    ),
  createMovement: (id: number, body: Record<string, unknown>) =>
    api<{ movement: RealMovement }>(`/real/accounts/${id}/movements`, {
      method: "POST",
      body,
    }),
  updateMovement: (id: number, movementId: number, body: Record<string, unknown>) =>
    api<{ movement: RealMovement }>(`/real/accounts/${id}/movements/${movementId}`, {
      method: "PATCH",
      body,
    }),
  deleteMovement: (id: number, movementId: number) =>
    api<{ ok: boolean }>(`/real/accounts/${id}/movements/${movementId}`, {
      method: "DELETE",
    }),
  previewImport: (id: number, file: File, mapping?: string, dateOrder = "dmy") => {
    const form = new FormData()
    form.append("file", file)
    if (mapping) form.append("mapping", mapping)
    form.append("date_order", dateOrder)
    return apiUpload<ImportPreview>(`/real/accounts/${id}/imports/preview`, form)
  },
  confirmImport: (id: number, batchId: number, allowPartial = false) =>
    api<{ created: number; skipped_duplicates: number; errors: { row: number; errors: string[] }[] }>(
      `/real/accounts/${id}/imports/${batchId}/confirm`,
      { method: "POST", body: { allow_partial: allowPartial } },
    ),
  discardImport: (id: number, batchId: number) =>
    api<{ ok: boolean }>(`/real/accounts/${id}/imports/${batchId}`, { method: "DELETE" }),
  documents: (accountId?: number) =>
    api<{ items: DocumentRecord[]; total: number }>(
      `/real/documents${accountId ? `?account_id=${accountId}` : ""}`,
    ),
  uploadDocument: (file: File, accountId?: number) => {
    const form = new FormData()
    form.append("file", file)
    if (accountId) form.append("account_id", String(accountId))
    return apiUpload<DocumentRecord>("/real/documents", form)
  },
  extractDocument: (id: number) =>
    api<{ document_id: number; status: string; extraction: DocumentRecord["extraction"] }>(
      `/real/documents/${id}/extract`,
      { method: "POST" },
    ),
  confirmDocument: (id: number, accountId: number, movement: Record<string, unknown>) =>
    api<{ document_id: number; status: string; movement: RealMovement }>(
      `/real/documents/${id}/confirm`,
      { method: "POST", body: { account_id: accountId, movement } },
    ),
  deleteDocument: (id: number) =>
    api<{ ok: boolean }>(`/real/documents/${id}`, { method: "DELETE" }),
  downloadDocument: (id: number) => apiDownload(`/real/documents/${id}/file`),
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
