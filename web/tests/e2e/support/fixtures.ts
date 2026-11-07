import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test"

/** Contraseña común de las cuentas de prueba (cumple el mínimo de 10). */
export const TEST_PASSWORD = "Contraseña-e2e-01"
export const TOKEN_KEY = "nexo.token"

export type TestUser = {
  email: string
  password: string
  name: string
}

/**
 * Correo único por test. La base de la suite es desechable, pero los tests se
 * repiten entre proyectos y en los reintentos de CI: el sufijo aleatorio evita
 * colisiones de `email_taken`.
 */
export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@nexo.test`
}

export function newUser(prefix = "e2e"): TestUser {
  return { email: uniqueEmail(prefix), password: TEST_PASSWORD, name: "Ana de Prueba" }
}

export type AuthPayload = {
  access_token: string
  token_type: string
  user: { id: number; email: string; display_name: string; role: string }
}

/**
 * IP de cliente derivada del correo. El backend limita los intentos por IP
 * (`auth-register`: 10/min) y la suite crea una cuenta por caso: sin esto, a
 * partir de la décima cuenta los tests fallarían por límite, no por la app.
 * Producción conserva sus límites; aquí solo se simulan clientes distintos.
 */
function clientIpFor(email: string): string {
  let hash = 7
  for (const char of email) hash = (hash * 31 + char.charCodeAt(0)) % 65521
  return `10.${(hash % 200) + 1}.${(Math.floor(hash / 200) % 250) + 1}.${(hash % 250) + 1}`
}

/** Cabeceras de una petición de autenticación aislada por cliente. */
function authHeaders(email: string): Record<string, string> {
  return { Accept: "application/json", "X-Forwarded-For": clientIpFor(email) }
}

/** Crea una cuenta contra la API real (sin pasar por la UI). */
export async function registerViaApi(
  request: APIRequestContext,
  user: TestUser,
): Promise<AuthPayload> {
  const response = await request.post("/api/v1/auth/register", {
    data: { email: user.email, password: user.password, display_name: user.name },
    headers: authHeaders(user.email),
  })
  expect(response.status(), `registro de ${user.email}`).toBe(201)
  return (await response.json()) as AuthPayload
}

/** Inicia sesión contra la API real y devuelve el token. */
export async function loginViaApi(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<AuthPayload> {
  const response = await request.post("/api/v1/auth/login", {
    data: { email, password },
    headers: authHeaders(email),
  })
  expect(response.status(), `login de ${email}`).toBe(200)
  return (await response.json()) as AuthPayload
}

/** Deja el token en localStorage antes de la primera navegación. */
export async function seedSession(page: Page, token: string): Promise<void> {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, token] as [string, string],
  )
}

type Fixtures = {
  /** Cuenta nueva con sesión ya sembrada en el navegador. */
  user: TestUser
  /** Contexto de API sin estado, con la misma baseURL que la aplicación. */
  api: APIRequestContext
}

export const test = base.extend<Fixtures>({
  api: async ({ playwright, baseURL }, use) => {
    const context = await playwright.request.newContext({ baseURL })
    await use(context)
    await context.dispose()
  },

  user: async ({ page }, use) => {
    const user = newUser()
    const auth = await registerViaApi(page.request, user)
    await seedSession(page, auth.access_token)
    await use(user)
  },
})

/** Cabecera de autorización para peticiones directas a la API. */
export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

export { expect }
