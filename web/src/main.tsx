import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./App"
import "./index.css"

const container = document.getElementById("root")
if (!container) throw new Error("No se encontró el nodo #root")

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// El service worker solo se registra en la build de producción: en desarrollo
// guardaría recursos antiguos y ocultaría cambios.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* sin service worker la app sigue funcionando, solo sin instalación offline */
    })
  })
}
