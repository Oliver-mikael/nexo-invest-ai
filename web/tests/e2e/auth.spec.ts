import { test, expect, newUser, registerViaApi, TOKEN_KEY, TEST_PASSWORD } from "./support/fixtures"

// Autenticación real contra la API y la UI de `/acceder`.
// Cada caso crea su propia cuenta: la base de datos de la suite es desechable,
// pero los usuarios nunca se reutilizan entre tests.

test.describe("autenticación", () => {
  test("registro: crea cuenta con email, password y nombre", async ({ page }) => {
    const user = newUser()

    await page.goto("/acceder")
    await expect(page.getByRole("heading", { name: "Entrar en tu cuenta" })).toBeVisible()

    await page.getByRole("button", { name: "Crear una" }).click()
    await expect(page.getByRole("heading", { name: "Crear cuenta" })).toBeVisible()

    await page.getByLabel("Nombre visible").fill(user.name)
    await page.getByLabel("Correo").fill(user.email)
    await page.getByLabel("Contraseña").fill(user.password)
    await page.getByRole("button", { name: "Crear cuenta" }).click()

    await expect(page).toHaveURL(/\/panel$/)
    await expect(page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) })).toBeVisible()
    await expect(page.getByRole("button", { name: "Salir" })).toBeVisible()
  })

  test("registro: no envía el formulario con contraseña corta", async ({ page }) => {
    await page.goto("/acceder")
    await page.getByRole("button", { name: "Crear una" }).click()

    await page.getByLabel("Correo").fill(newUser().email)
    const password = page.getByLabel("Contraseña")
    await password.fill("corta")

    // La validación nativa del formulario detiene el envío antes de llamar a la API.
    await expect(password).toHaveJSProperty("validity.valid", false)
    await page.getByRole("button", { name: "Crear cuenta" }).click()

    await expect(page).toHaveURL(/\/acceder$/)
    expect(await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_KEY)).toBeNull()
  })

  test("login: entra con credenciales correctas y saluda por su nombre", async ({ page }) => {
    const user = newUser()
    await registerViaApi(page.request, user)

    await page.goto("/acceder")
    await page.getByLabel("Correo").fill(user.email)
    await page.getByLabel("Contraseña").fill(user.password)
    await page.getByRole("button", { name: "Entrar", exact: true }).click()

    await expect(page).toHaveURL(/\/panel$/)
    await expect(page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) })).toBeVisible()
  })

  test("login: contraseña incorrecta muestra error y no inicia sesión", async ({ page }) => {
    const user = newUser()
    await registerViaApi(page.request, user)

    await page.goto("/acceder")
    await page.getByLabel("Correo").fill(user.email)
    await page.getByLabel("Contraseña").fill("contraseña-mala-01")
    await page.getByRole("button", { name: "Entrar", exact: true }).click()

    await expect(page.getByText("Correo o contraseña incorrectos.")).toBeVisible()
    await expect(page).toHaveURL(/\/acceder$/)
    expect(await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_KEY)).toBeNull()
  })

  test("login: un correo ya registrado no se puede volver a registrar", async ({ page }) => {
    const user = newUser()
    await registerViaApi(page.request, user)

    await page.goto("/acceder")
    await page.getByRole("button", { name: "Crear una" }).click()
    await page.getByLabel("Nombre visible").fill(user.name)
    await page.getByLabel("Correo").fill(user.email)
    await page.getByLabel("Contraseña").fill(TEST_PASSWORD)
    await page.getByRole("button", { name: "Crear cuenta" }).click()

    await expect(page.getByText("Ya existe una cuenta con ese correo.")).toBeVisible()
    await expect(page).toHaveURL(/\/acceder$/)
  })

  test("destino: tras iniciar sesión vuelve a la ruta privada solicitada", async ({ page }) => {
    const user = newUser()
    await registerViaApi(page.request, user)

    await page.goto("/informes")
    await expect(page).toHaveURL(/\/acceder\?destino=/)
    expect(new URL(page.url()).searchParams.get("destino")).toBe("/informes")

    await page.getByLabel("Correo").fill(user.email)
    await page.getByLabel("Contraseña").fill(user.password)
    await page.getByRole("button", { name: "Entrar", exact: true }).click()

    await expect(page).toHaveURL(/\/informes$/)
    await expect(page.getByRole("heading", { name: "Informes" })).toBeVisible()
  })

  test("logout: cierra la sesión, borra el token y bloquea de nuevo la ruta privada", async ({
    page,
  }) => {
    const user = newUser()
    const auth = await registerViaApi(page.request, user)

    // El token se siembra una sola vez: así se comprueba que el cierre de sesión
    // lo elimina de verdad en lugar de restaurarlo en la siguiente navegación.
    await page.goto("/acceder")
    await page.evaluate(
      ([key, token]) => window.localStorage.setItem(key, token),
      [TOKEN_KEY, auth.access_token] as [string, string],
    )
    await page.goto("/panel")
    await expect(page.getByRole("heading", { name: new RegExp(`Hola, ${user.name}`) })).toBeVisible()

    await page.getByRole("button", { name: "Salir" }).click()

    await expect(page).toHaveURL(/\/acceder$/)
    expect(await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_KEY)).toBeNull()

    await page.goto("/panel")
    await expect(page).toHaveURL(/\/acceder\?destino=/)
  })
})
