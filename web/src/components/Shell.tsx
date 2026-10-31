import { useEffect, useState } from "react"
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom"
import { useAuth } from "../lib/auth"

const NAV = [
  { to: "/panel", label: "Panel", icon: "◧" },
  { to: "/empresas", label: "Empresas", icon: "▤" },
  { to: "/investigacion", label: "Investigación", icon: "◎" },
  { to: "/informes", label: "Informes", icon: "❐" },
  { to: "/cartera", label: "Cartera", icon: "◈" },
  { to: "/ajustes", label: "Ajustes", icon: "⚙" },
]

type InstallPromptEvent = Event & { prompt: () => Promise<void> }

function useInstallPrompt() {
  const [event, setEvent] = useState<InstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(
    typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches,
  )

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault()
      setEvent(e as InstallPromptEvent)
    }
    const onInstalled = () => {
      setInstalled(true)
      setEvent(null)
    }
    window.addEventListener("beforeinstallprompt", handler)
    window.addEventListener("appinstalled", onInstalled)
    return () => {
      window.removeEventListener("beforeinstallprompt", handler)
      window.removeEventListener("appinstalled", onInstalled)
    }
  }, [])

  const install = async () => {
    if (!event) return
    await event.prompt()
    setEvent(null)
  }

  return { canInstall: Boolean(event) && !installed, install }
}

export function Shell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { canInstall, install } = useInstallPrompt()
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener("online", up)
    window.addEventListener("offline", down)
    return () => {
      window.removeEventListener("online", up)
      window.removeEventListener("offline", down)
    }
  }, [])

  useEffect(() => {
    setMenuOpen(false)
  }, [navigate])

  return (
    <div className="min-h-screen pb-24 md:pb-0">
      {!online ? (
        <div className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-600">
          Sin conexión. El panel y los cálculos necesitan red; las investigaciones siguen en el servidor.
        </div>
      ) : null}

      <header className="sticky top-0 z-30 border-b border-ink-900/10 bg-paper/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Link to="/panel" className="flex items-baseline gap-2 no-underline">
            <span className="font-display text-xl tracking-tight text-ink-900">Nexo</span>
            <span className="hidden text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-300 sm:inline">
              Invest AI
            </span>
          </Link>

          <nav className="hidden flex-1 items-center gap-1 md:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm no-underline transition-colors ${
                    isActive ? "bg-ink-900 text-paper" : "text-ink-500 hover:bg-ink-900/5 hover:text-ink-900"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {canInstall ? (
              <button type="button" onClick={install} className="btn-ghost hidden text-xs sm:inline-flex">
                Instalar app
              </button>
            ) : null}
            {user ? (
              <div className="flex items-center gap-2">
                <span className="hidden text-xs text-ink-500 lg:inline">{user.display_name || user.email}</span>
                <button
                  type="button"
                  onClick={async () => {
                    await logout()
                    navigate("/acceder")
                  }}
                  className="btn-ghost text-xs"
                >
                  Salir
                </button>
              </div>
            ) : (
              <Link to="/acceder" className="btn-dark text-xs no-underline">
                Entrar
              </Link>
            )}
            <button
              type="button"
              aria-label="Abrir menú"
              className="btn-ghost px-2 py-2 md:hidden"
              onClick={() => setMenuOpen((open) => !open)}
            >
              ☰
            </button>
          </div>
        </div>

        {menuOpen ? (
          <nav className="border-t border-ink-900/10 bg-paper px-4 py-3 md:hidden">
            <div className="grid grid-cols-2 gap-2">
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) =>
                    `rounded-lg border px-3 py-2 text-sm no-underline ${
                      isActive
                        ? "border-moss-600/30 bg-moss-100 text-moss-600"
                        : "border-ink-900/10 bg-white/70 text-ink-600"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          </nav>
        ) : null}
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-ink-900/10 bg-paper/95 backdrop-blur md:hidden">
        <div className="grid grid-cols-6">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 py-2 text-[10px] no-underline ${
                  isActive ? "text-moss-600" : "text-ink-300"
                }`
              }
            >
              <span className="text-base leading-none">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
