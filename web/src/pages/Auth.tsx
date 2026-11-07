import { useState } from "react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { useAuth } from "../lib/auth"
import { ApiError } from "../lib/api"
import { ErrorNotice, Field } from "../components/ui"

export function Auth() {
  const { user, login, register } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const destination = params.get("destino") ?? "/panel"
  const [mode, setMode] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={destination} replace />

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === "login") await login(email.trim(), password)
      else await register(email.trim(), password, name.trim())
      navigate(destination, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 0
            ? "No hay conexión con el servidor."
            : err.code === "invalid_credentials"
              ? "Correo o contraseña incorrectos."
              : err.code === "email_taken"
                ? "Ya existe una cuenta con ese correo."
                : err.message,
        )
      } else {
        setError("No se pudo completar la operación.")
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden flex-col justify-between bg-ink-900 p-10 text-paper lg:flex">
        <Link to="/" className="font-display text-2xl no-underline text-paper">
          Nexo
        </Link>
        <div>
          <p className="chip bg-white/10 text-paper/70">Investigación auditada</p>
          <h1 className="mt-6 max-w-md font-display text-4xl leading-tight">
            Un informe que puedes discutir cifra por cifra.
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-paper/60">
            El motor calcula. Los modelos investigan. El auditor señala lo que no tiene respaldo.
            Tú conservas el criterio y ves los supuestos.
          </p>
        </div>
        <p className="text-xs text-paper/40">
          Datos de SEC EDGAR · Sin recomendaciones de inversión · Cartera simulada
        </p>
      </div>

      <div className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <Link to="/" className="font-display text-2xl text-ink-900 no-underline">
              Nexo
            </Link>
          </div>
          <h2 className="font-display text-3xl tracking-tight">
            {mode === "login" ? "Entrar en tu cuenta" : "Crear cuenta"}
          </h2>
          <p className="mt-2 text-sm text-ink-500">
            {mode === "login"
              ? "Accede al panel, a tus investigaciones y a tu cartera simulada."
              : "Necesitas una cuenta para guardar investigaciones e informes."}
          </p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            {mode === "register" ? (
              <Field label="Nombre visible">
                <input
                  className="field"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  placeholder="Ana"
                  maxLength={120}
                />
              </Field>
            ) : null}
            <Field label="Correo">
              <input
                className="field"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="tu@correo.com"
              />
            </Field>
            <Field
              label="Contraseña"
              hint={mode === "register" ? "Mínimo 10 caracteres." : undefined}
            >
              <input
                className="field"
                type="password"
                required
                minLength={mode === "register" ? 10 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder="••••••••••"
              />
            </Field>

            {error ? <ErrorNotice message={error} /> : null}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? "Procesando…" : mode === "login" ? "Entrar" : "Crear cuenta"}
            </button>
          </form>

          <p className="mt-6 text-sm text-ink-500">
            {mode === "login" ? "¿No tienes cuenta?" : "¿Ya tienes cuenta?"}{" "}
            <button
              type="button"
              className="font-semibold text-moss-600 underline-offset-2 hover:underline"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login")
                setError(null)
              }}
            >
              {mode === "login" ? "Crear una" : "Entrar"}
            </button>
          </p>
          <p className="mt-8 text-[11px] leading-relaxed text-ink-300">
            Al continuar aceptas que Nexo Invest AI es una herramienta de investigación y no un
            servicio de asesoramiento financiero. No se ejecutan operaciones reales.
          </p>
        </div>
      </div>
    </div>
  )
}
