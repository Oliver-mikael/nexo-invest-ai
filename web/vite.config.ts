import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// El backend FastAPI sirve `dist/` en producción; en desarrollo Vite hace proxy de
// `/api` para evitar CORS y mantener las rutas relativas en el cliente.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
})
