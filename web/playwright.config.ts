import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"

// Rutas derivadas del propio fichero de configuración: funciona igual lanzando
// los tests desde `web/` que desde la raíz del repositorio.
const webDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(webDir, "..")

// Datos exclusivos de la suite: base SQLite, caché de la SEC y documentos.
// Nunca se usa la base de desarrollo. `var/` está ignorado por Git.
const e2eDataDir = path.join(repoRoot, "var", "e2e")
const e2eDatabase = path.join(e2eDataDir, "e2e.db")

const API_PORT = Number(process.env.E2E_API_PORT ?? 8000)
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5180)

const apiUrl = `http://127.0.0.1:${API_PORT}`
const webUrl = `http://127.0.0.1:${WEB_PORT}`

export default defineConfig({
  testDir: path.join(webDir, "tests", "e2e"),
  // Los tests comparten la base de datos de la suite: se ejecutan en serie para
  // que los estados (carteras, ajustes, movimientos) sean deterministas.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium-desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
      metadata: { viewport: "desktop" },
    },
    {
      name: "chromium-mobile",
      use: { ...devices["Pixel 7"] },
      metadata: { viewport: "mobile" },
    },
  ],
  webServer: [
    {
      // Backend real con base de datos desechable. El prefijo `rm` garantiza que
      // cada ejecución empiece sin usuarios ni datos de la anterior.
      command: `rm -f "${e2eDatabase}" "${e2eDatabase}-wal" "${e2eDatabase}-shm" && exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --log-level warning`,
      cwd: repoRoot,
      url: `${apiUrl}/api/v1/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXO_ENV: "e2e",
        NEXO_DATABASE_URL: `sqlite:///${e2eDatabase}`,
        NEXO_AUTO_CREATE_SCHEMA: "1",
        NEXO_STATIC_DIR: path.join(e2eDataDir, "no-static"),
        NEXO_SEC_CACHE_DIR: path.join(e2eDataDir, "sec-cache"),
        NEXO_DOCUMENTS_DIR: path.join(e2eDataDir, "documents"),
        NEXO_SEC_CONTACT: "e2e@nexo.invalid",
        // Sin proveedores de IA: el estado del panel y de ajustes es determinista
        // y ninguna investigación intenta salir a la red.
        NEXO_AI_DISABLED: "1",
        NEXO_AI_FAKE_PROVIDER: "",
        NEXO_AI_OPENAI_KEY: "",
        NEXO_AI_ANTHROPIC_KEY: "",
        NEXO_AI_GEMINI_KEY: "",
        NEXO_AI_LOCAL_BASE_URL: "",
        // Sin trabajos de fondo automáticos durante la suite.
        NEXO_DATA_SYNC_INTERVAL_MINUTES: "0",
        NEXO_ALERT_CHECK_INTERVAL_MINUTES: "0",
        NEXO_RATE_LIMIT_PER_MINUTE: "600",
        NEXO_WORKER_THREADS: "1",
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      // Vite en un puerto propio para no chocar con el servidor de desarrollo.
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      cwd: webDir,
      url: webUrl,
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
})
