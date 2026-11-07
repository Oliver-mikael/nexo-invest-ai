# Validación E2E con navegador (Fase 1.2)

> **Estado: validada con ejecución real.** La suite de Playwright se ejecutó en este
> entorno con Chromium 156.0.8078.4 (headless shell) sobre la aplicación completa
> —backend FastAPI + frontend Vite— y terminó en verde en los dos proyectos:
> `chromium-desktop` (30 pasan, 5 omitidos) y `chromium-mobile` (33 pasan, 2 omitidos).
> Los omitidos son casos deliberadamente exclusivos del otro viewport.
>
> Rama: `feat/e2e-browser-validation` (base `feat/platform-v1`, merge-base `84585a2`).

## 1. Qué se conservó de la Fase 1.1

- `web/playwright.config.ts` y `web/tests/e2e/auth.spec.ts` existían y se ampliaron, no se
  reescribieron desde cero.
- Dependencias `playwright` y `@playwright/test` 1.64.1 ya estaban en `web/package.json`.
- La corrección de `__dirname` (módulo ESM) se sustituyó por una resolución de rutas
  robusta basada en `import.meta.url`, válida lanzando los tests desde `web/` o desde la raíz.
- `docs/E2E_VALIDATION.md` y la sección del README se actualizaron con resultados reales.

## 2. Arquitectura de la suite

```
web/tests/e2e/
├── support/fixtures.ts   fixtures y utilidades compartidas
├── auth.spec.ts          registro, login, validación, destino y logout (7)
├── navigation.spec.ts    landing, protección de rutas, shell y 404 (6)
├── pages.spec.ts         estados reales de cada pantalla (10)
├── security.spec.ts      autorización, aislamiento, revocación y secretos (7)
└── mobile.spec.ts        navegación y layout móvil + manifiesto PWA (5)
```

- **Backend real, datos desechables.** `playwright.config.ts` arranca
  `uvicorn app.main:app` con `NEXO_DATABASE_URL=sqlite:///…/var/e2e/e2e.db`, caché de la
  SEC y documentos dentro de `var/e2e/`, y borra la base al inicio de cada ejecución. En
  producción esos límites y esa base no cambian: es configuración exclusiva de la suite.
- **Sin proveedores de IA reales** (`NEXO_AI_DISABLED=1`, claves neutralizadas): el estado
  del panel y de ajustes es determinista y ninguna investigación intenta salir a la red.
- **Servidores propios.** Vite se levanta en el puerto 5180 con `--strictPort` para no
  chocar con el servidor de desarrollo; Playwright espera `/api/v1/health` y la raíz web
  antes de ejecutar. Los servidores los gestiona Playwright y mueren al terminar.
- **Aislamiento de datos por test.** Cada caso crea su propia cuenta con correo único; los
  datos financieros (cartera, cuenta real, ajustes) quedan ligados a ese usuario y no se
  reutilizan. La base se descarta entre ejecuciones.
- **Fixtures reutilizables** (`user`, `api`) y helpers (`registerViaApi`, `loginViaApi`,
  `seedSession`, `bearer`). Sin esperas arbitrarias: todas las esperas son condiciones de
  Playwright (`expect(...).toBeVisible()`, `toHaveURL`, `toHaveValue`, `toHaveAttribute`).
- **Artefactos solo ante fallo**: `trace`, `screenshot` y `video` en `retain-on-failure`,
  informe HTML siempre.

### Casos por área

| Área | Casos |
|------|-------|
| Autenticación | registro por UI, contraseña corta bloqueada, login correcto, contraseña incorrecta, correo duplicado, retorno a `?destino`, logout que borra el token y vuelve a bloquear la ruta |
| Navegación | landing pública, 13 rutas privadas sin sesión → `/acceder?destino=…`, titulares de las 13 pantallas, menú de escritorio, desplegable de automatización, 404 interno |
| Comportamiento | panel con estado del sistema y estados vacíos, empresas (vacío, búsqueda sin resultados, apertura de ticker), investigación (formulario, perfiles, sin proveedores), informes (contador y filtros), ajustes (guardado persistente), cartera simulada (creación + recarga), cartera real (cuenta + depósito) |
| Seguridad | API privada sin token, token inválido, cartera de otro usuario (404 y listado vacío), revocación tras logout, ausencia de secretos en la UI y en localStorage, errores sin trazas ni rutas internas, validación de entrada en servidor |
| Móvil (Pixel 7) | menú hamburguesa completo, barra inferior de 5 accesos, formulario de acceso usable, sin desbordamiento horizontal en 6 rutas, manifiesto PWA servido |

## 3. Chromium en este entorno

El disco del workspace estaba al 97-98 % (3,9 GB, ~88 MB libres). Se liberaron cachés
re-descargables (`npm cache clean --force`, `pip cache purge`) y se instaló el binario
headless, que es más pequeño que Chrome for Testing completo:

```bash
cd web
node node_modules/.bin/playwright install --only-shell chromium
# chromium_headless_shell-1248 + ffmpeg-1013
```

Con `headless: true` (por defecto en los dos proyectos), Playwright usa exactamente ese
binario. Comprobación directa:

```
titulo: ok
version: 156.0.8078.4
```

No se usó ningún navegador del sistema ni un Chrome preinstalado: no existían.

## 4. Comandos y resultados exactos

Desde `web/`:

| Comando | Resultado |
|---------|-----------|
| `npm ci --no-audit --no-fund` | OK |
| `npm run typecheck` (`tsc -b --noEmit`) | OK |
| `npm run build` | OK (dist generado) |
| `playwright test --project chromium-desktop` | **30 passed, 5 skipped** (59,8 s) |
| `playwright test --project chromium-mobile` | **33 passed, 2 skipped** (1,1 min) |

Desde la raíz:

| Comando | Resultado |
|---------|-----------|
| `python -m ruff check src app tests` | OK |
| `pytest tests/ --ignore=tests/platform` | **397 passed, 1 skipped** |
| `pytest tests/platform` | **120 passed** |
| Total Python | **517 passed, 1 skipped, 0 failed** |

Cada ejecución crea su propia base `var/e2e/e2e.db`, así que los resultados son
reproducibles y no dependen de datos previos.

## 5. Fallo preexistente de pytest: causa y corrección

`test_price_sync_stores_daily_closes_with_adjusted_separate` fallaba con
`assert True is False` en `result["stale"]`.

Evidencia recogida:

1. **No es una regresión de esta fase.** El fichero no existe en la base:
   `git cat-file -e 84585a2:tests/platform/test_market_data.py` → *Not a valid object name*.
   El test lo introdujo el commit `c96ed63` («fase 5»).
2. **No es un problema ambiental ni de espacio.** La prueba falla igual con `/tmp` libre y
   pasa con el mismo entorno si se amplía la ventana de frescura:
   `NEXO_DATA_STALE_AFTER_DAYS=30 pytest -k test_price_sync_stores_daily_closes → passed`.
3. **Causa real: test dependiente del reloj.** El payload simulado usa fechas fijas
   (`latest_as_of = 2026-10-30`) y `DataSyncService` calcula
   `stale = (hoy - latest).days > data_stale_after_days` con umbral 5. El 2026-11-07 la
   diferencia es de 8 días → `stale=True`, mientras el test esperaba `False`. El test
   empezó a fallar el 2026-11-05, cinco días después de escribirse.

Corrección aplicada (solo prueba, sin tocar lógica financiera): el caso fija
`data_stale_after_days=3650` con `dataclasses.replace`, porque su objeto es comprobar el
almacenamiento de cierres y ajustados. La detección de datos viejos sigue cubierta por
`test_price_sync_flags_stale_history`, que sí prueba la marca `stale=True`.

## 6. Defectos reales detectados y corregidos

1. **Cartera simulada: el formulario de creación no se podía enviar.**
   `web/src/pages/Portfolio.tsx` declaraba `min="100"` con `step="1000"`, de modo que solo
   eran válidos 100, 1100, 2100… El valor por defecto (100 000) y cualquier importe
   redondo incumplían `stepMismatch` y el navegador bloqueaba el envío **sin mostrar error**.
   Corregido a `step="100"`; el test comprueba `validity.valid` con el valor por defecto y
   con 50 000.
2. **Etiquetas ambiguas que rompían selectores estables** (no es un defecto de producto,
   pero sí de accesibilidad): en móvil el botón «Abrir menú» comparte subcadena con
   «Abrir», y los accesos de la barra inferior incluyen el icono en el nombre accesible.
   Los tests usan `exact: true` o regex para no depender de coincidencias parciales.

## 7. CI con Chromium

`.github/workflows/ci.yml` incorpora el job `e2e`:

1. `actions/checkout@v4`, Node 22 con caché de `web/package-lock.json`, Python 3.12.
2. `pip install -e ".[dev]"` (backend que la suite arranca).
3. `npm ci --no-audit --no-fund`.
4. `npx playwright install --with-deps chromium` (binario + librerías de sistema).
5. `npm run typecheck` y `npm run build`.
6. `npm run e2e` con `CI=true` (1 worker, 1 reintento, informe HTML).
7. `actions/upload-artifact@v4` con `web/playwright-report/` y `web/test-results/`
   siempre (`if: always()`), retención 14 días.

El job no necesita espacio local del workspace ni servicios externos: el runner instala
el navegador y la suite levanta backend y Vite.

**Validación remota pendiente de autorización**: el workflow se ejecuta en
`pull_request` y en `push` a `main`. Para verlo correr en GitHub Actions hay que publicar
la rama y abrir el PR; no se hizo push ni se abrió PR en esta fase.

## 8. Limitaciones reales

- **Cobertura condicionada a la red.** Las pantallas que dependen de datos vivos de la SEC
  (ficha de empresa con DCF y sensibilidad, generación de informes del motor, ejecución de
  investigaciones e importación de documentos) no se validan de extremo a extremo: en un
  entorno sin salida a Internet el motor no puede descargar estados financieros. Sí se
  comprueba la navegación a `/empresas/:ticker` y el estado vacío del explorador.
- **La cartera simulada se prueba sin posiciones.** Valorar una posición exige cotización
  de Yahoo; los casos cubren creación, métricas y persistencia, no el precio de mercado.
- **PWA parcial.** Se verifica que el manifiesto se sirve con nombre, iconos y `display`,
  y el layout móvil. No se prueba instalación real, service worker offline ni empaquetado
  Capacitor/APK (requiere Android SDK).
- **Un fallo intermitente no reproducido.** En una ejecución completa del proyecto móvil,
  el caso de revocación de sesión falló una vez en una comparación de código de estado
  (`toBe`), y volvió a pasar en las dos ejecuciones completas siguientes, sin errores en el
  log del backend. No se ha identificado la causa; CI aplica `retries: 1` y conviene
  vigilarlo.
- **Límite de intentos por IP.** El backend limita `auth-register` a 10/min por IP. La suite
  crea una cuenta por caso y presenta un `X-Forwarded-For` derivado del correo para simular
  clientes distintos, sin tocar los límites de producción. Ese mismo detalle sugiere una
  observación de seguridad ajena a esta fase: `client_key()` confía en `X-Forwarded-For`
  sin validar un proxy de confianza, así que un cliente directo puede eludir el límite.
- **Escritorio simulado con Chromium** (1440×900). No se han probado Firefox, WebKit ni
  Safari reales.

## 9. Pendientes

1. Publicar la rama y abrir el PR para que el job `e2e` corra en GitHub Actions.
2. Añadir datos de mercado sembrados (fixtures de la SEC) para cubrir ficha de empresa,
   DCF, sensibilidad, informes del motor y una investigación completa sin red.
3. Valoración con precios deterministas (proveedor estático) para cubrir operaciones de la
   cartera simulada.
4. Validación PWA real: instalación, offline con service worker y empaquetado con Capacitor.
5. Vigilar el fallo intermitente del caso de revocación de sesión.
