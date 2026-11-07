import { test, expect, newUser, registerViaApi, bearer, TOKEN_KEY } from "./support/fixtures"

// Comprobaciones de seguridad sobre la implementación real: la autorización se
// hace en el backend, así que se verifica contra la API además de la UI.

const PRIVATE_ENDPOINTS = [
  "/api/v1/dashboard",
  "/api/v1/portfolios",
  "/api/v1/reports",
  "/api/v1/research",
  "/api/v1/real/overview",
  "/api/v1/settings",
]

test.describe("seguridad", () => {
  test("la API privada rechaza peticiones sin token", async ({ api }) => {
    for (const endpoint of PRIVATE_ENDPOINTS) {
      const response = await api.get(endpoint)
      expect(response.status(), `sin token en ${endpoint}`).toBe(401)
    }
  })

  test("un token inválido no abre recursos privados", async ({ api }) => {
    const response = await api.get("/api/v1/portfolios", {
      headers: { Authorization: "Bearer token-inventado" },
    })
    expect(response.status()).toBe(401)
  })

  test("un usuario no puede leer la cartera de otro", async ({ api }) => {
    const owner = await registerViaApi(api, newUser("e2e-dueno"))
    const outsider = await registerViaApi(api, newUser("e2e-otro"))
    const ownerHeaders = bearer(owner.access_token)
    const outsiderHeaders = bearer(outsider.access_token)

    const created = await api.post("/api/v1/portfolios", {
      headers: ownerHeaders,
      data: { name: "Cartera privada", starting_cash: 10000, benchmark: "SPY" },
    })
    expect(created.status()).toBe(201)
    const { id } = await created.json()

    // El dueño la ve; otra cuenta recibe 404 (no 403) para no revelar su existencia.
    expect((await api.get(`/api/v1/portfolios/${id}`, { headers: ownerHeaders })).status()).toBe(200)
    expect((await api.get(`/api/v1/portfolios/${id}`, { headers: outsiderHeaders })).status()).toBe(
      404,
    )

    const listing = await api.get("/api/v1/portfolios", { headers: outsiderHeaders })
    expect((await listing.json()).total).toBe(0)
  })

  test("cerrar sesión revoca el token en el servidor", async ({ api }) => {
    const auth = await registerViaApi(api, newUser("e2e-revocado"))
    const headers = bearer(auth.access_token)

    expect((await api.get("/api/v1/auth/me", { headers })).status()).toBe(200)

    const logout = await api.post("/api/v1/auth/logout", { headers })
    expect(logout.status()).toBe(200)

    const after = await api.get("/api/v1/auth/me", { headers })
    expect(after.status()).toBe(401)
  })

  test("la interfaz no contiene secretos ni claves de proveedores", async ({ page, user }) => {
    await page.goto("/ajustes")
    await expect(page.getByRole("heading", { name: "Ajustes" })).toBeVisible()

    const text = (await page.locator("body").innerText()) ?? ""
    expect(text).not.toMatch(/sk-[A-Za-z0-9_-]{16,}/)
    expect(text).not.toMatch(/NEXO_[A-Z_]*(KEY|SECRET|TOKEN)\s*=\s*\S+/)
    expect(text).not.toMatch(/Traceback \(most recent call last\)/)
    expect(text).not.toContain(user.password)

    // El único dato persistido en el navegador es el token de sesión.
    const storageKeys = await page.evaluate(() => Object.keys(window.localStorage).sort())
    expect(storageKeys).toEqual(["nexo.token"])
    expect(page.url()).not.toContain("access_token")
  })

  test("los errores de la API no filtran rutas internas ni trazas", async ({ api }) => {
    const auth = await registerViaApi(api, newUser("e2e-errores"))
    const headers = bearer(auth.access_token)

    for (const endpoint of ["/api/v1/reports/999999", "/api/v1/research/999999"]) {
      const response = await api.get(endpoint, { headers })
      expect(response.status(), endpoint).toBe(404)

      const body = JSON.stringify(await response.json())
      expect(body).not.toContain("Traceback")
      expect(body).not.toContain("/home/")
      expect(body).not.toContain("sqlite")
      expect(body).toMatch(/not_found|no existe/i)
    }
  })

  test("el token sirve en la petición inmediatamente posterior a emitirlo", async ({ api }) => {
    // Regresión: la sesión se confirmaba al cerrar la dependencia de base de
    // datos, después de responder, así que la primera petición con el token
    // recién creado podía recibir 401 de forma intermitente.
    for (let attempt = 1; attempt <= 5; attempt += 1) {
      const auth = await registerViaApi(api, newUser("e2e-inmediato"))
      const me = await api.get("/api/v1/auth/me", { headers: bearer(auth.access_token) })
      expect(me.status(), `intento ${attempt}`).toBe(200)
    }
  })

  test("cerrar sesión borra el token antes de que el servidor responda", async ({
    page,
    user,
  }) => {
    await page.goto("/panel")
    await expect(page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) })).toBeVisible()

    // La revocación remota tarda 1,5 s: la sesión local no puede esperarla.
    await page.route("**/api/v1/auth/logout", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await route.continue()
    })

    const token = () => page.evaluate((key) => window.localStorage.getItem(key), TOKEN_KEY)
    await page.getByRole("button", { name: "Salir" }).click()

    await expect(page).toHaveURL(/\/acceder/)
    await expect.poll(token, { timeout: 1000 }).toBeNull()
  })

  test("si la revocación falla, la sesión local se cierra igualmente", async ({ page, user }) => {
    await page.goto("/panel")
    await expect(page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) })).toBeVisible()

    await page.route("**/api/v1/auth/logout", (route) => route.abort())
    await page.getByRole("button", { name: "Salir" }).click()

    await expect(page).toHaveURL(/\/acceder/)
    expect(await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_KEY)).toBeNull()

    // La persistencia entre navegaciones se cubre en auth.spec con una sesión
    // sembrada una sola vez: el fixture `user` vuelve a inyectar el token en
    // cada carga y una recarga aquí no probaría nada del cierre de sesión.
  })

  test("el registro valida el correo y la contraseña en el servidor", async ({ api }) => {
    const response = await api.post("/api/v1/auth/register", {
      data: { email: "no-es-un-correo", password: "123", display_name: "" },
    })

    expect(response.status()).toBe(422)
    const body = await response.json()
    expect(body.error.code).toBe("validation_error")
    expect(JSON.stringify(body)).not.toContain("Traceback")
  })
})
