import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { ApiError, authApi, getToken, setToken, type User } from "./api"

type AuthValue = {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(Boolean(getToken()))
  // Cada inicio o cierre de sesión invalida las peticiones de perfil en vuelo:
  // sin esto, una respuesta lenta de `/auth/me` podía restaurar al usuario
  // después de haber cerrado sesión (o borrar el token recién obtenido).
  const generation = useRef(0)

  const refresh = useCallback(async () => {
    const epoch = generation.current
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await authApi.me()
      if (epoch !== generation.current) return
      setUser(me)
    } catch (error) {
      if (epoch !== generation.current) return
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setToken(null)
      }
      setUser(null)
    } finally {
      if (epoch === generation.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (email: string, password: string) => {
    const response = await authApi.login(email, password)
    generation.current += 1
    setToken(response.access_token)
    setUser(response.user)
    setLoading(false)
  }, [])

  const register = useCallback(async (email: string, password: string, name: string) => {
    const response = await authApi.register(email, password, name)
    generation.current += 1
    setToken(response.access_token)
    setUser(response.user)
    setLoading(false)
  }, [])

  const logout = useCallback(async () => {
    const token = getToken()
    // El estado local se cierra primero: el token deja de existir en el
    // navegador aunque la petición de revocación falle o tarde, y ya no hay
    // forma de que una respuesta anterior restaure la sesión.
    generation.current += 1
    setToken(null)
    setUser(null)
    setLoading(false)
    if (!token) return
    try {
      // Se envía el token capturado porque el almacenamiento ya está limpio.
      await authApi.logout(token)
    } catch {
      /* sin red el servidor caducará la sesión por TTL */
    }
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ user, loading, login, register, logout, refresh }),
    [user, loading, login, register, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth debe usarse dentro de AuthProvider")
  return context
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-ink-900/15 border-t-moss-600" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to={`/acceder?destino=${encodeURIComponent(location.pathname)}`} replace />
  }
  return <>{children}</>
}
