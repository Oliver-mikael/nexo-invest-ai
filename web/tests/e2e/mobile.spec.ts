import { test, expect } from "./support/fixtures"

// Estos casos solo tienen sentido en el proyecto `chromium-mobile` (Pixel 7).
// No se declara compatibilidad PWA completa: se comprueba el renderizado, la
// navegación táctil y que el manifiesto se sirva.
test.skip(({ isMobile }) => !isMobile, "Solo se ejecuta en el proyecto móvil")

test.describe("móvil", () => {
  test("el botón de menú abre la navegación completa", async ({ page, user }) => {
    await page.goto("/panel")
    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()

    await page.getByRole("button", { name: "Abrir menú" }).click()

    for (const label of ["Empresas", "Investigación", "Informes", "Ajustes", "Tesis", "Tareas"]) {
      await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible()
    }

    await page.getByRole("link", { name: "Tesis", exact: true }).click()
    await expect(page).toHaveURL(/\/tesis$/)
    await expect(page.getByRole("heading", { name: "Tesis de inversión" })).toBeVisible()
    // El menú se cierra al navegar.
    await expect(page.getByRole("link", { name: "Tesis", exact: true })).toHaveCount(0)
  })

  test("la barra inferior navega entre las cinco secciones", async ({ page, user }) => {
    await page.goto("/panel")
    const bottomNav = page.locator("nav.fixed")

    for (const { label, route } of [
      { label: "Empresas", route: "/empresas" },
      { label: "Investigación", route: "/investigacion" },
      { label: "Cartera real", route: "/cartera-real" },
      { label: "Simulada", route: "/cartera" },
      { label: "Panel", route: "/panel" },
    ]) {
      // Cada acceso de la barra incluye su icono en el nombre accesible.
      await bottomNav.getByRole("link", { name: new RegExp(label) }).click()
      await expect(page, `barra inferior a ${route}`).toHaveURL(new RegExp(`${route}$`))
    }

    await expect(bottomNav.getByRole("link")).toHaveCount(5)
  })

  test("el formulario de acceso es usable en pantalla pequeña", async ({ page }) => {
    await page.goto("/acceder")

    await expect(page.getByLabel("Correo")).toBeVisible()
    await expect(page.getByLabel("Contraseña")).toBeVisible()

    const submit = page.getByRole("button", { name: "Entrar", exact: true })
    await expect(submit).toBeInViewport()

    await page.getByRole("button", { name: "Crear una" }).click()
    await expect(page.getByLabel("Nombre visible")).toBeInViewport()
    await expect(page.getByRole("button", { name: "Crear cuenta" })).toBeInViewport()
  })

  test("las pantallas principales no desbordan horizontalmente", async ({ page, user }) => {
    for (const route of ["/panel", "/empresas", "/cartera-real", "/cartera", "/ajustes", "/acceder"]) {
      await page.goto(route)
      const overflow = await page.evaluate(() => {
        const root = document.documentElement
        return root.scrollWidth - root.clientWidth
      })
      expect(overflow, `desbordamiento en ${route}`).toBeLessThanOrEqual(1)
    }
  })

  test("el manifiesto PWA se sirve con nombre e iconos", async ({ api }) => {
    const response = await api.get("/manifest.webmanifest")
    expect(response.status()).toBe(200)

    const manifest = await response.json()
    expect(manifest.name).toMatch(/Nexo/)
    expect(manifest.icons.length).toBeGreaterThanOrEqual(2)
    expect(manifest.display).toBe("standalone")
  })
})
