import { useCallback, useEffect, useRef, useState } from "react"
import { ApiError } from "./api"

type State<T> = {
  data: T | null
  error: string | null
  loading: boolean
  code: string | null
}

/**
 * Carga asíncrona con cancelación y recarga manual.
 * No guarda estado global: cada pantalla pide sus datos al backend.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true, code: null })
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setState((previous) => ({ ...previous, loading: true, error: null }))
    loaderRef
      .current()
      .then((data) => {
        if (active) setState({ data, error: null, loading: false, code: null })
      })
      .catch((error: unknown) => {
        if (!active) return
        if ((error as Error).name === "AbortError") return
        const message =
          error instanceof ApiError
            ? error.status === 0
              ? "Sin conexión con el servidor."
              : error.message
            : "No se pudieron cargar los datos."
        setState({
          data: null,
          error: message,
          loading: false,
          code: error instanceof ApiError ? error.code : null,
        })
      })
    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((value) => value + 1), [])

  return { ...state, reload }
}
