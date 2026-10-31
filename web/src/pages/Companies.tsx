import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { companiesApi } from "../lib/api"
import { Badge, Card, ErrorNotice, Skeleton } from "../components/ui"

const SUGGESTIONS = ["AAPL", "MSFT", "NVDA", "KO", "JPM"]

export function Companies() {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const [items, setItems] = useState<{ ticker: string; name: string; sector: string; industry: string; cik: number | null }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [manual, setManual] = useState("")

  useEffect(() => {
    let active = true
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await companiesApi.search(query)
        if (active) setItems(response.items)
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Error al buscar")
      } finally {
        if (active) setLoading(false)
      }
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [query])

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-300">Explorador</p>
        <h1 className="mt-1 font-display text-4xl tracking-tight">Empresas</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-500">
          Busca por nombre, ticker, sector o industria entre las empresas ya consultadas, o abre
          cualquier ticker de la SEC para descargar sus estados financieros.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <input
          className="field"
          placeholder="Buscar: AAPL, tecnología, Apple…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Buscar empresas"
        />
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            const value = manual.trim().toUpperCase()
            if (value) navigate(`/empresas/${value}`)
          }}
        >
          <input
            className="field font-mono uppercase"
            placeholder="Ticker"
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            maxLength={12}
            aria-label="Abrir ticker"
          />
          <button type="submit" className="btn-dark whitespace-nowrap">
            Abrir
          </button>
        </form>
      </div>

      {error ? <ErrorNotice message={error} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-[0.08em] text-ink-300">Sugerencias</span>
        {SUGGESTIONS.map((ticker) => (
          <Link
            key={ticker}
            to={`/empresas/${ticker}`}
            className="rounded-md border border-ink-900/10 bg-white px-2.5 py-1 font-mono text-xs text-ink-700 no-underline hover:border-moss-600/40 hover:text-moss-600"
          >
            {ticker}
          </Link>
        ))}
      </div>

      {loading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <p className="text-sm text-ink-500">
            No hay empresas guardadas{query ? ` que coincidan con “${query}”` : ""}. Abre un ticker
            concreto para descargar sus datos de la SEC y quedará en el explorador.
          </p>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((company) => (
            <Link
              key={company.ticker}
              to={`/empresas/${company.ticker}`}
              className="surface block p-4 no-underline transition-colors hover:border-moss-600/30"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-semibold text-ink-900">{company.ticker}</span>
                {company.cik ? <Badge tone="muted">CIK {company.cik}</Badge> : null}
              </div>
              <p className="mt-1 truncate text-sm text-ink-700">{company.name}</p>
              <p className="mt-0.5 truncate text-xs text-ink-300">
                {[company.sector, company.industry].filter(Boolean).join(" · ") || "Sin clasificar"}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
