# Validación E2E y endurecimiento de seguridad (Fases 1.2 y 1.3)

> **Estado: validado con ejecución real y publicado.** La suite de Playwright se
> ejecutó con Chromium 156.0.8078.4 (headless shell) sobre la aplicación completa
> —backend FastAPI + frontend Vite— y terminó en verde en los dos proyectos.
> El trabajo está integrado en `feat/platform-v1` (PR #2 hacia `main`) y el job
> `e2e` de GitHub Actions se ejecuta en ese PR.
>
> Base de la integración: `origin/feat/platform-v1` en `f5b87c4`, que ya contenía
> los tres commits enviados previamente al PR #2. La integración fue
> *fast-forward*: no hubo merge ni commits reescritos.

## 1. Qué se conservó de fases anteriores

- `web/playwright.config.ts` y `web/tests/e2e/auth.spec.ts` de la Fase 1.1 se
  ampliaron; no se reescribió la suite desde cero.
- Dependencias `playwright` y `@playwright/test` 1.64.1 ya estaban declaradas.
- La resolución de rutas de la Fase 1.1 se sustituyó por una basada en
  `import.meta.url`, válida tanto desde `web/` como desde la raíz del repositorio.
- El backend, el motor financiero y las pantallas existentes no se sustituyeron
  por versiones simplificadas: solo se corrigieron defectos concretos.

## 2. Arquitectura de la suite

```
web/tests/e2e/
├── support/fixtures.ts   fixtures y utilidades compartidas
├── auth.spec.ts          registro, login, validación, destino y logout (7)
├── navigation.spec.ts    landing, protección de rutas, shell y 404 (6)
├── pages.spec.ts         estados reales de cada pantalla (10)
├── security.spec.ts      autorización, aislamiento, sesión y secretos (10)
└── mobile.spec.ts        navegación y layout móvil + manifiesto PWA (5)
```

38 casos por proyecto (escritorio 1440×900 y Pixel 7); los casos exclusivos de un
viewport se omiten en el otro con `test.skip`.

- **Backend real, datos desechables.** `playwright.config.ts` arranca
  `uvicorn app.main:app` con `NEXO_DATABASE_URL=sqlite:///…/var/e2e/e2e.db`, caché
  de la SEC y documentos dentro de `var/e2e/`, y borra la base al inicio de cada
  ejecución. Nunca se usa la base de desarrollo.
- **Sin proveedores de IA** (`NEXO_AI_DISABLED=1`, claves neutralizadas) y sin
  trabajos de fondo: el estado del panel y de ajustes es determinista y ninguna
  prueba intenta salir a la red.
- **Servidores propios.** Vite en el puerto 5180 con `--strictPort`; Playwright
  espera `/api/v1/health` y la raíz web antes de ejecutar y apaga ambos al
  terminar.
- **Aislamiento por test.** Cada caso crea su propia cuenta con correo único; los
  datos quedan ligados a ese usuario y la base se descarta entre ejecuciones.
- **Sin esperas arbitrarias**: todas las esperas son condiciones de Playwright.
- **Artefactos solo ante fallo**: `trace`, `screenshot` y `video` en
  `retain-on-failure`, informe HTML siempre.
- **Proxies de confianza.** El backend solo interpreta `X-Forwarded-For` si la
  conexión llega de una red declarada. La suite declara loopback
  (`NEXO_TRUSTED_PROXIES=127.0.0.1,::1`) para poder simular clientes distintos;
  producción no declara nada por defecto.

### Casos por área

| Área | Casos |
|------|-------|
| Autenticación | registro por UI, contraseña corta bloqueada, login correcto, contraseña incorrecta, correo duplicado, retorno a `?destino`, logout que borra el token y vuelve a bloquear la ruta |
| Navegación | landing pública, 13 rutas privadas sin sesión → `/acceder?destino=…`, titulares de las 13 pantallas, menú de escritorio, desplegable de automatización, 404 interno |
| Comportamiento | panel con estado del sistema y estados vacíos, empresas (vacío, búsqueda sin resultados, apertura de ticker), investigación (formulario, perfiles, sin proveedores), informes (contador y filtros), ajustes (guardado persistente), cartera simulada (creación + recarga), cartera real (cuenta + depósito) |
| Seguridad | API privada sin token, token inválido, cartera de otro usuario (404 y listado vacío), revocación tras logout, token utilizable en la petición inmediatamente posterior al registro, cierre de sesión con revocación lenta, cierre de sesión con revocación fallida, ausencia de secretos en la UI y en localStorage, errores sin trazas ni rutas internas, validación de entrada en servidor |
| Móvil (Pixel 7) | menú hamburguesa completo, barra inferior de 5 accesos, formulario de acceso usable, sin desbordamiento horizontal en 6 rutas, manifiesto PWA servido |

## 3. Chromium en este entorno

El disco del workspace estaba casi lleno. Se liberaron cachés re-descargables
(`npm cache clean --force`, `pip cache purge`) y se instaló el binario headless,
más pequeño que Chrome for Testing completo:

```bash
cd web
node node_modules/.bin/playwright install --only-shell chromium
# chromium_headless_shell-1248 + ffmpeg-1013
```

Con `headless: true`, Playwright usa exactamente ese binario. Comprobación
directa: `titulo: ok` · `version: 156.0.8078.4`.

## 4. Comandos y resultados exactos

Ejecutados sobre la rama integrada `feat/platform-v1` en `2854d58`, desde la raíz
del repositorio salvo donde se indica:

| Comando | Resultado |
|---------|-----------|
| `ruff check src app tests` | OK |
| `pytest tests --ignore=tests/platform` | **397 passed, 1 skipped** |
| `pytest tests/platform` | **146 passed** |
| Total Python | **543 passed, 1 skipped, 0 failed** |
| `npm run typecheck` (`tsc -b --noEmit`) | OK |
| `npm run build` | OK (`dist/` 357 kB JS, 30 kB CSS) |
| `playwright test --project chromium-desktop` | **33 passed, 5 skipped** (1,0 min) |
| `playwright test --project chromium-mobile` | **36 passed, 2 skipped** (1,1 min) |
| `playwright test --project=chromium-desktop tests/e2e/security.spec.ts --repeat-each=10` | **100 passed** |

Cada ejecución crea su propia base `var/e2e/e2e.db`, así que los resultados son
reproducibles. La prueba omitida de Python es la histórica que necesita red.

## 5. Fallo preexistente de pytest: causa y corrección

`test_price_sync_stores_daily_closes_with_adjusted_separate` fallaba con
`assert True is False` en `result["stale"]`.

Evidencia recogida:

1. **No es una regresión de esta fase.** El fichero no existe en la base
   (`git cat-file -e 84585a2:tests/platform/test_market_data.py` → *Not a valid
   object name*). El test lo introdujo el commit `c96ed63` («fase 5»).
2. **No es un problema ambiental.** Pasa con el mismo entorno si se amplía la
   ventana de frescura: `NEXO_DATA_STALE_AFTER_DAYS=30 pytest -k
   test_price_sync_stores_daily_closes → passed`.
3. **Causa real: test dependiente del reloj.** El payload simulado usa fechas
   fijas (`2026-10-30`) y `DataSyncService` calcula
   `stale = (hoy - latest).days > data_stale_after_days` con umbral 5. El
   2026-11-07 la diferencia es de 8 días → `stale=True`, mientras el test
   esperaba `False`.

Corrección (solo prueba, sin tocar lógica financiera): el caso fija
`data_stale_after_days=3650` con `dataclasses.replace`, porque su objeto es el
almacenamiento de cierres y ajustados. La detección de datos viejos sigue
cubierta por `test_price_sync_flags_stale_history`.

## 6. Defectos reales detectados y corregidos

### 6.1 El token recién emitido podía no valer (causa de la intermitencia del logout)

La intermitencia conocida se atribuía al cierre de sesión. Al repetir el fichero
de seguridad (`--repeat-each=8`) el fallo apareció con más detalle: **1 de 16
ejecuciones falló en el 401 de `/auth/me` inmediatamente después del registro**,
no en el logout.

Causa: `get_db` confirmaba la transacción al desmontar la dependencia, es decir,
**después** de enviar la respuesta. La petición siguiente podía ejecutarse en
otro hilo del pool antes de ese commit y no encontrar la fila de la sesión → 401
intermitente. El mismo patrón afectaba a la revocación: el cliente podía
comprobar el token antes de que el borrado estuviera confirmado.

Correcciones:

- `register` y `login` confirman la transacción antes de devolver el token.
- `logout` confirma la revocación antes de responder 200.
- El frontend limpia el token y el usuario **antes** de llamar al servidor, envía
  el token capturado para revocarlo y descarta respuestas de `/auth/me` que
  lleguen después de un cierre de sesión (contador de generación).

Verificación: 100 ejecuciones del fichero de seguridad sin fallos (antes fallaba
1 de 16) y 5 pruebas nuevas de ciclo de vida de sesión.

### 6.2 Identidad de cliente falsificable (`X-Forwarded-For`)

`client_key()` devolvía el primer valor de la cabecera sin comprobar quién la
enviaba: un cliente directo podía rotar IPs falsas y esquivar los límites de
registro (10/min) y acceso (12/min).

Correcciones (`app/deps.py`, `app/config.py`):

- La identidad es la IP de la conexión TCP y la cabecera se ignora salvo que la
  conexión llegue de una red declarada en `NEXO_TRUSTED_PROXIES` (IP o CIDR).
- Con proxy de confianza, la cadena se recorre **de derecha a izquierda**
  descartando los saltos de confianza, que es el orden en que los proxies añaden
  direcciones.
- Se admiten `ip:puerto` y `[ipv6]:puerto`; las direcciones se normalizan
  (`::ffff:1.2.3.4` → `1.2.3.4`).
- Si algún salto no es una IP válida, o la cadena supera 10 saltos, la cabecera se
  descarta entera: fallo cerrado y nunca se propaga texto arbitrario como clave.
- Una entrada inválida en `NEXO_TRUSTED_PROXIES` no autoriza nada.
- La auditoría de autenticación usa la misma identidad que los límites.

21 pruebas en `tests/platform/test_client_identity.py`: cliente directo con
cabecera falsa, proxy confiable, proxy no confiable, cadenas múltiples, cabecera
ausente, entradas malformadas, puertos, IPv6, configuración inválida y evasión del
límite extremo a extremo (10 registros con IP falsa distinta agotan el cupo de la
IP real; detrás de un proxy declarado cada IP reenviada tiene su propio cupo).

### 6.3 Cartera simulada: el formulario no se podía enviar

`web/src/pages/Portfolio.tsx` declaraba `min="100"` con `step="1000"`, de modo que
solo eran válidos 100, 1100, 2100… El valor por defecto (100 000) y cualquier
importe redondo incumplían `stepMismatch` y el navegador bloqueaba el envío **sin
mostrar error**. Corregido a `step="100"`; el test comprueba `validity.valid`.

### 6.4 Etiquetas ambiguas (accesibilidad de los selectores)

En móvil «Abrir menú» comparte subcadena con «Abrir», y los accesos de la barra
inferior incluyen el icono en el nombre accesible. Los tests usan `exact: true` o
regex para no depender de coincidencias parciales.

## 7. CI con Chromium

`.github/workflows/ci.yml` mantiene los jobs existentes (`tests` en Python 3.10 y
3.12 con ruff, imports y CLI; `web` con typecheck y build) y añade el job `e2e`:

1. `actions/checkout@v4`, Node 22 con caché de `web/package-lock.json`, Python 3.12.
2. `pip install -e ".[dev]"` (backend que la suite arranca).
3. `npm ci --no-audit --no-fund`.
4. `npx playwright install --with-deps chromium` (binario + librerías de sistema).
5. `npm run typecheck` y `npm run build`.
6. `npm run e2e` con `CI=true` (1 worker, 1 reintento, informe HTML).
7. `actions/upload-artifact@v4` con `web/playwright-report/` y
   `web/test-results/` siempre (`if: always()`), retención 14 días.

El job no necesita servicios externos ni credenciales: solo instala el navegador y
la suite levanta backend y Vite.

### Ejecución real en GitHub Actions

Run [42397855482](https://github.com/Oliver-mikael/nexo-invest-ai/actions/runs/42397855482)
sobre `2854d58`, PR #2 (`feat/platform-v1` → `main`): **4 jobs, todos en verde**.

| Job | Resultado | Duración |
|-----|-----------|----------|
| Motor y API · Python 3.12 | **543 passed, 1 skipped** + ruff OK | 44 s |
| Motor y API · Python 3.10 | **543 passed, 1 skipped** + ruff OK | 67 s |
| Web y PWA | typecheck y build OK | 18 s |
| E2E · Chromium real | **69 passed** (7 omitidos, 76 ejecuciones) | 1 min 58 s |

El artefacto `playwright-report` (281 kB) se subió correctamente, incluido el
informe HTML de esa ejecución. El runner avisa de que Node 20 está obsoleto en
las acciones (`checkout`, `setup-node`, `setup-python`, `upload-artifact`); no
afecta al resultado y se resolverá al actualizar las versiones de las acciones.

## 8. Limitaciones reales

- **Cobertura condicionada a la red.** Las pantallas que dependen de datos vivos de
  la SEC (ficha de empresa con DCF y sensibilidad, generación de informes del
  motor, investigaciones e importación de documentos) no se validan de extremo a
  extremo sin salida a Internet. Sí se comprueba la navegación y los estados
  vacíos.
- **Cartera simulada sin posiciones.** Valorar una posición exige cotización
  externa; los casos cubren creación, métricas y persistencia.
- **PWA parcial.** Se verifica el manifiesto y el layout móvil; no instalación
  real, service worker offline ni empaquetado Capacitor/APK.
- **Un navegador.** Solo Chromium (escritorio simulado 1440×900 y Pixel 7). No se
  probaron Firefox, WebKit ni Safari reales.
- **Límites por IP detrás de un proxy.** Si se despliega detrás de nginx/Traefik y
  no se declara `NEXO_TRUSTED_PROXIES`, todos los clientes comparten el cupo de la
  IP del proxy (más estricto, nunca más laxo). Es la configuración segura por
  defecto y el operador debe declarar el proxy.
- **Cambio de contraseña no revoca otras sesiones.** El cierre de sesión revoca el
  token actual; las demás sesiones de la cuenta siguen válidas hasta su TTL. No es
  una regresión de esta fase y no se ha cambiado el modelo de sesiones.

## 9. Cómo reproducir

```bash
# Suite completa de Python (sin red)
python3 -m pytest

# Interfaz
cd web
npm ci
npx playwright install --with-deps chromium
npm run e2e            # los dos proyectos
npm run e2e:headed     # con navegador visible
npm run e2e:report     # informe HTML de la última ejecución

# Caso concreto, repetido para detectar intermitencia
npx playwright test tests/e2e/security.spec.ts --repeat-each=10
```

## 10. Commits incorporados en la integración

```
2854d58 fix(auth): confirmar la sesión antes de responder y cerrar sesión sin carreras
03b9911 feat(security): decidir la identidad del cliente solo con proxies explícitos
79c7790 ci(e2e): ejecutar Playwright con Chromium en GitHub Actions
220c95a test(e2e): suite funcional en Chromium con backend aislado y datos propios
32e8975 test(market-data): desacoplar el caso de cierres ajustados del reloj
09133df fix(web): permitir importes redondos al crear una cartera
```

Sobre la base remota `f5b87c4` (PR #2), que ya incluía el trabajo de fases
anteriores. La rama `main` no se ha modificado ni se ha fusionado ningún PR.
