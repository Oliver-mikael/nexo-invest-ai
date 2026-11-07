import { test, expect } from "./support/fixtures"

// Rutas privadas declaradas en `web/src/App.tsx`, protegidas por `RequireAuth`.
const PRIVATE_ROUTES = [
  "/panel",
  "/empresas",
  "/investigacion",
  "/informes",
  "/cartera-real",
  "/cartera",
  "/datos",
  "/seguimiento",
  "/alertas",
  "/tesis",
  "/backtests",
  "/tareas",
  "/ajustes",
]

// Titular visible de cada pantalla, tal como está implementado en las páginas.
const HEADINGS: { route: string; heading: string | RegExp }[] = [
  { route: "/panel", heading: /^Hola,/ },
  { route: "/empresas", heading: "Empresas" },
  { route: "/investigacion", heading: "Investigación" },
  { route: "/informes", heading: "Informes" },
  { route: "/cartera-real", heading: "Cartera real" },
  { route: "/cartera", heading: "Cartera" },
  { route: "/datos", heading: "Datos de mercado" },
  { route: "/seguimiento", heading: "Seguimiento" },
  { route: "/alertas", heading: "Alertas" },
  { route: "/tesis", heading: "Tesis de inversión" },
  { route: "/backtests", heading: "Backtests" },
  { route: "/tareas", heading: "Tareas" },
  { route: "/ajustes", heading: "Ajustes" },
]

test.describe("landing pública", () => {
  test("muestra la propuesta y lleva al acceso", async ({ page }) => {
    await page.goto("/")

    await expect(
      page.getByRole("heading", { name: /Cada cifra tiene un documento detrás/ }),
    ).toBeVisible()
    await expect(page.getByRole("link", { name: "Crear cuenta" })).toBeVisible()

    await page.getByRole("link", { name: "Crear cuenta" }).click()
    await expect(page).toHaveURL(/\/acceder$/)
    await expect(page.getByRole("heading", { name: "Entrar en tu cuenta" })).toBeVisible()
  })
})

test.describe("protección de rutas privadas", () => {
  test("sin sesión, cada ruta privada redirige a /acceder con su destino", async ({ page }) => {
    for (const route of PRIVATE_ROUTES) {
      await page.goto(route)
      await expect(page, `destino de ${route}`).toHaveURL(/\/acceder\?destino=/)

      const url = new URL(page.url())
      expect(url.pathname, `ruta de ${route}`).toBe("/acceder")
      expect(url.searchParams.get("destino"), `destino de ${route}`).toBe(route)
    }
  })
})

test.describe("navegación autenticada", () => {
  test("cada pantalla privada renderiza su titular", async ({ page, user }) => {
    await page.goto("/panel")
    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()

    for (const { route, heading } of HEADINGS) {
      await page.goto(route)
      await expect(
        page.getByRole("heading", { name: heading, exact: typeof heading === "string" }),
        `titular de ${route}`,
      ).toBeVisible()
      // Ninguna pantalla debe caer en el 404 interno del router.
      await expect(page.getByText("Esta página no existe")).toHaveCount(0)
    }
  })

  test("el menú de escritorio navega entre las secciones principales", async ({
    page,
    user,
    isMobile,
  }) => {
    test.skip(isMobile, "El menú superior está oculto en móvil; se cubre en mobile.spec.ts")

    await page.goto("/panel")
    const nav = page.getByRole("navigation").first()

    for (const { label, route } of [
      { label: "Empresas", route: "/empresas" },
      { label: "Investigación", route: "/investigacion" },
      { label: "Informes", route: "/informes" },
      { label: "Cartera real", route: "/cartera-real" },
      { label: "Simulada", route: "/cartera" },
      { label: "Datos", route: "/datos" },
      { label: "Ajustes", route: "/ajustes" },
      { label: "Panel", route: "/panel" },
    ]) {
      await nav.getByRole("link", { name: label, exact: true }).click()
      await expect(page, `navegación a ${route}`).toHaveURL(new RegExp(`${route}$`))
    }

    // Se termina en el panel y el saludo confirma la sesión del usuario creado.
    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()
  })

  test("el desplegable de automatización lleva a sus pantallas", async ({ page, user, isMobile }) => {
    test.skip(isMobile, "El desplegable de automatización solo existe en escritorio")

    await page.goto("/panel")
    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()
    const nav = page.getByRole("navigation").first()
    const automation = nav.getByRole("button", { name: /Automatización/ })

    for (const { label, route } of [
      { label: "Seguimiento", route: "/seguimiento" },
      { label: "Alertas", route: "/alertas" },
      { label: "Tesis", route: "/tesis" },
      { label: "Backtests", route: "/backtests" },
      { label: "Tareas", route: "/tareas" },
    ]) {
      await automation.click()
      await expect(automation).toHaveAttribute("aria-expanded", "true")
      await nav.getByRole("link", { name: label, exact: true }).click()
      await expect(page, `navegación a ${route}`).toHaveURL(new RegExp(`${route}$`))
    }
  })

  test("una ruta inexistente muestra el 404 interno dentro del shell", async ({ page, user }) => {
    await page.goto("/panel")
    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()
    await page.goto("/ruta-que-no-existe")

    await expect(page.getByRole("heading", { name: "Esta página no existe" })).toBeVisible()
    await page.getByRole("link", { name: "Volver al panel" }).click()
    await expect(page).toHaveURL(/\/panel$/)
  })
})
