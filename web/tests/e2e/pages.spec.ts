import { test, expect } from "./support/fixtures"

// Estados reales de cada pantalla con datos recién creados:
// carga de datos del backend, estados vacíos y confirmaciones de escritura.

test.describe("panel", () => {
  test("muestra el estado del sistema y los estados vacíos", async ({ page, user }) => {
    await page.goto("/panel")

    await expect(
      page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) }),
    ).toBeVisible()

    // Datos del backend: motor y presupuesto, no cálculos del navegador.
    await expect(page.getByText("Motor financiero")).toBeVisible()
    await expect(page.getByText("Presupuesto IA")).toBeVisible()
    await expect(page.getByText("Trabajos activos")).toBeVisible()

    // Estados vacíos de un usuario recién creado.
    await expect(page.getByText("Aún no hay investigaciones. Analiza una empresa")).toBeVisible()
    await expect(page.getByText("Sin informes guardados.")).toBeVisible()
    await expect(page.getByText("Todavía no has abierto ninguna empresa.")).toBeVisible()
    await expect(page.getByText("Aún no hay cuentas reales.")).toBeVisible()
  })
})

test.describe("empresas", () => {
  test("sin empresas guardadas explica cómo abrir un ticker", async ({ page, user }) => {
    await page.goto("/empresas")
    await expect(page.getByRole("heading", { name: "Empresas" })).toBeVisible()

    await expect(page.getByText(/No hay empresas guardadas/)).toBeVisible()
    for (const ticker of ["AAPL", "MSFT", "NVDA", "KO", "JPM"]) {
      await expect(page.getByRole("link", { name: ticker, exact: true })).toBeVisible()
    }
  })

  test("la búsqueda informa del término cuando no hay coincidencias", async ({ page, user }) => {
    await page.goto("/empresas")
    await page.getByLabel("Buscar empresas").fill("zzz-sin-resultados")

    await expect(page.getByText(/que coincidan con “zzz-sin-resultados”/)).toBeVisible()
  })

  test("abrir un ticker navega a su ficha", async ({ page, user }) => {
    await page.goto("/empresas")
    await page.getByLabel("Abrir ticker").fill("msft")
    // `exact` evita que coincida también el botón «Abrir menú» del shell móvil.
    await page.getByRole("button", { name: "Abrir", exact: true }).click()

    await expect(page).toHaveURL(/\/empresas\/MSFT$/)
  })
})

test.describe("investigación", () => {
  test("muestra el formulario, los perfiles y el historial vacío", async ({ page, user }) => {
    await page.goto("/investigacion")
    await expect(page.getByRole("heading", { name: "Investigación", exact: true })).toBeVisible()

    // Sin ticker no se puede encolar.
    await expect(page.getByRole("button", { name: "Iniciar investigación" })).toBeDisabled()

    await expect(page.getByRole("radio", { name: /Básico/ })).toBeVisible()
    await expect(page.getByRole("radio", { name: /Estándar/ })).toBeVisible()
    await expect(page.getByRole("radio", { name: /Profundo/ })).toBeVisible()

    // El backend informa de que no hay proveedores de IA configurados.
    await expect(page.getByText(/No hay proveedores de IA configurados/)).toBeVisible()
    await expect(page.getByText("Sin investigaciones todavía.")).toBeVisible()
  })

  test("el perfil y el presupuesto se pueden cambiar antes de enviar", async ({ page, user }) => {
    await page.goto("/investigacion")

    await page.getByLabel("Ticker").fill("AAPL")
    await expect(page.getByRole("button", { name: "Iniciar investigación" })).toBeEnabled()

    await page.getByRole("radio", { name: /Básico/ }).check()
    await expect(page.getByText("Perfil básico: sin llamadas a modelos.")).toBeVisible()

    await page.getByLabel("Presupuesto (USD)").fill("0.25")
    await expect(page.getByLabel("Presupuesto (USD)")).toHaveValue("0.25")

    await page.getByLabel("Presupuesto (USD)").fill("99")
    await expect(page.getByLabel("Presupuesto (USD)")).toHaveValue("99")
  })
})

test.describe("informes", () => {
  test("lista vacía, contador y filtros por tipo", async ({ page, user }) => {
    await page.goto("/informes")
    await expect(page.getByRole("heading", { name: "Informes" })).toBeVisible()

    await expect(page.getByText("0 informe(s)")).toBeVisible()
    await expect(page.getByText(/Sin informes\. Genera uno desde la ficha/)).toBeVisible()

    for (const filter of ["Investigación", "Motor", "Todos"]) {
      await page.getByRole("button", { name: filter, exact: true }).click()
      await expect(page.getByText("0 informe(s)")).toBeVisible()
    }
  })
})

test.describe("ajustes", () => {
  test("guarda las preferencias y las conserva al recargar", async ({ page, user }) => {
    await page.goto("/ajustes")
    await expect(page.getByRole("heading", { name: "Ajustes" })).toBeVisible()

    // La cuenta mostrada es la del usuario autenticado.
    await expect(page.getByText("Nombre", { exact: true })).toBeVisible()

    await page.getByLabel("Benchmark de la cartera").fill("qqq")
    await page.getByLabel("Años de proyección").fill("7")
    await page.getByRole("button", { name: "Guardar cambios" }).click()

    await expect(page.getByText("Preferencias guardadas.")).toBeVisible()

    await page.reload()
    await expect(page.getByLabel("Benchmark de la cartera")).toHaveValue("QQQ")
    await expect(page.getByLabel("Años de proyección")).toHaveValue("7")
  })
})

test.describe("cartera simulada", () => {
  test("crea una cartera, muestra métricas y la conserva al recargar", async ({ page, user }) => {
    await page.goto("/cartera")
    await expect(page.getByRole("heading", { name: "Cartera" })).toBeVisible()

    await expect(page.getByRole("heading", { name: "Crear cartera", exact: true })).toBeVisible()

    // El valor por defecto debe ser enviable: un `step` mal alineado con `min`
    // bloquea el formulario en silencio (defecto real detectado por esta suite).
    const cash = page.getByLabel("Efectivo inicial")
    await expect(cash).toHaveJSProperty("validity.valid", true)

    await cash.fill("50000")
    await expect(cash).toHaveJSProperty("validity.valid", true)
    await page.getByRole("button", { name: "Crear cartera" }).click()

    await expect(page.getByText("Valor total")).toBeVisible()
    await expect(page.getByText("Sin posiciones todavía.")).toBeVisible()

    await page.reload()
    await expect(page.getByText("Valor total")).toBeVisible()
    await expect(page.getByRole("button", { name: "Registrar operación" })).toBeVisible()
  })
})

test.describe("cartera real", () => {
  test("crea una cuenta y registra un depósito", async ({ page, user }) => {
    await page.goto("/cartera-real")
    await expect(page.getByRole("heading", { name: "Cartera real" })).toBeVisible()

    await expect(page.getByText("Crear la primera cuenta real")).toBeVisible()
    await page.getByLabel("Bróker (texto, sin credenciales)").fill("Bróker de prueba")
    await page.getByLabel("País del bróker").fill("es")
    await page.getByRole("button", { name: "Crear cuenta" }).click()

    // Al crear la cuenta aparece su resumen con pestañas.
    await expect(page.getByRole("heading", { name: "Cuenta principal" })).toBeVisible()
    await page.getByRole("button", { name: "Movimientos" }).click()
    await expect(page.getByText("Sin movimientos. Registra un depósito para empezar.")).toBeVisible()

    await page.getByLabel("Tipo").selectOption("deposit")
    await page.getByLabel("Importe").fill("10000")
    await page.getByRole("button", { name: "Registrar movimiento" }).click()

    await expect(
      page.getByText("Movimiento registrado y validado contra el libro completo."),
    ).toBeVisible()
    await expect(page.getByText("Depósito").first()).toBeVisible()
  })
})
