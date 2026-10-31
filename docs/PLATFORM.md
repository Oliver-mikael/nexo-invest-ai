# PLATFORM — Nexo Invest AI 2.0

Documento de arquitectura y decisiones de la plataforma web, PWA, multi-IA y cartera real
multimercado. Complementa a `ARCHITECTURE.md`, que describe el motor financiero y las reglas
contables, y no se ha reescrito.

## 1. Qué se añadió y qué se conservó

**Conservado sin cambios de comportamiento:** todo `src/nexo_invest` (SEC EDGAR,
iXBRL, CompanyFacts, Nasdaq, precios, métricas, DCF, escenarios, sensibilidad,
backtesting, estrategias, informes) y sus 397 pruebas.

**Añadido:**

| Capa | Ubicación | Responsabilidad |
| --- | --- | --- |
| API | `app/api/v1/` | Contrato HTTP versionado, validación y errores |
| Servicios | `app/services/` | Motor, investigación, trabajos, cartera, precios, exportación |
| Orquestador IA | `app/ai/` | Proveedores, roles, presupuesto y auditoría de cifras |
| Persistencia | `app/models.py`, `migrations/` | Usuarios, sesiones, empresas, trabajos, informes, cartera, consumo |
| Web/PWA | `web/` | SPA React + TypeScript + Tailwind, manifest y service worker |
| Despliegue | `Dockerfile`, `docker-compose.yml`, `env.example` | Imagen única, Postgres, migraciones |

La regla de oro se mantiene: **el frontend no calcula nada financiero**. Recibe
cifras ya calculadas por el backend.

## 1.1 Cartera real multimercado (2.0)

La cartera real es un módulo independiente. No reutiliza `portfolios`, `positions` ni
`trades` de la simulación; comparte usuarios, sesiones, auditoría y límites.

```
markets ──► instruments ──► quotes / fx_rates
                 │                 │
                 ▼                 ▼
 real_accounts ──► real_movements ──► accounting.py (Decimal, FIFO/media, TWR/XIRR)
       │                 │                          │
       │                 ├── import_batches ◄── CSV/XLSX
       │                 └── documents ◄── OCR local + revisión humana
       ▼
 overview por moneda base (no suma divisas distintas)
```

- El alta de un movimiento se valida reproduciendo **todo** el libro con el candidato;
  si deja efectivo negativo, vende más de lo disponible o incumple una regla, se rechaza.
- Los tipos de cambio se guardan por movimiento; la valoración usa la última cotización
  visible con su fecha y fuente. Si falta, la posición queda sin valorar.
- La importación tiene tres pasos: subir → previsualizar/mapear → confirmar. La vista previa
  no escribe movimientos. Los duplicados se detectan por `external_id` o huella económica.
- El OCR local devuelve campos propuestos y `review_required`; el documento solo se vincula
  a un movimiento tras una confirmación humana con correcciones.

## 2. Flujo de una investigación

```
SEC EDGAR ──► ProvenanceRegistry ──► FinancialMetrics ──► DCF + sensibilidad
                                              │
                                              ▼
                                   Expediente (evidence ledger)
                                              │
              ┌───────────────────────────────┼───────────────────────────┐
              ▼               ▼               ▼               ▼           ▼
        Investigador     Analista       Contrario        Auditor     Coordinador
              └───────────────┴───────────────┴───────────────┴───────────┘
                                              │
                                    Informe de 18 secciones
                                              │
                        Auditoría determinista de cifras (app/ai/audit.py)
```

1. El motor descarga y valida los datos. Si no hay `NEXO_SEC_CONTACT`, responde
   503 y explica qué falta; no inventa cifras.
2. Se construye un **expediente** con cada métrica, su periodo, su procedencia y
   su documento de origen (más las valoraciones por escenario).
3. Los roles de IA reciben el expediente y deben citar `evidence_ids`.
4. El auditor determinista compara las cifras del texto con el expediente
   (tolerancia 2 % en importes y 1 pp en porcentajes) y marca las que no
   rastrean. Es código, no otra opinión de un modelo.
5. El informe conserva desacuerdos y limitaciones; nunca promedia consensos.

## 3. Orquestador multi-IA

- Interfaz única `LLMProvider.complete(...)` (`app/ai/base.py`).
- Adaptadores: OpenAI y compatibles (`/chat/completions`), Anthropic
  (`/v1/messages`), Gemini (`:generateContent`), servidor local y `FakeProvider`
  para pruebas.
- Perfiles: `basic` (0 llamadas), `standard` (5 roles, modelo económico) y
  `deep` (5 roles, modelos fuertes en análisis y coordinación).
- Presupuesto por trabajo, comprobado **antes** de cada llamada; al agotarse se
  detiene y se guarda el informe parcial. Consumo mensual por usuario en
  `usage_counters`.
- Reintentos: 2 intentos por rol ante error de proveedor o JSON inválido, con
  espera corta. Un rol caído no tumba la investigación.
- Tokens y coste se registran por rol y por trabajo, con tabla de precios
  configurable (`NEXO_AI_PRICES`).
- Las claves se leen solo en el servidor (`NEXO_AI_*_KEY`). No existe endpoint
  que las devuelva; `/settings` expone únicamente nombre, tipo y modelos.

## 4. Persistencia y trabajos

- SQLAlchemy 2.0 + Alembic. SQLite en desarrollo (`var/nexo.db`) y PostgreSQL en
  producción (`DATABASE_URL`). `NEXO_AUTO_CREATE_SCHEMA=0` desactiva la creación
  automática: el esquema lo gobiernan las migraciones.
- `research_jobs` guarda estado, etapa, presupuesto, coste, intentos y el id del
  informe. El estado vive en la base de datos, no en memoria.
- Al arrancar, los trabajos en `running` se reencolan si quedan intentos; si no,
  se marcan fallidos con explicación. Los cancelados antes de empezar no se
  reencolan.
- El ejecutor es un `ThreadPoolExecutor` del proceso. **Límite conocido:** con
  varias réplicas hace falta una cola compartida (Redis/RQ, Celery, Dramatiq).
  El diseño ya separa `JobRunner` de la API para poder cambiarlo.

## 5. API v1

Documentación interactiva: `/docs` (OpenAPI en `/openapi.json`). Errores
uniformes:

```json
{"error": {"code": "engine_unavailable", "message": "...", "details": {}}}
```

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/api/v1/health` | Estado del servicio y de la base de datos |
| POST | `/api/v1/auth/register` | Crear cuenta (contraseña ≥ 10 caracteres) |
| POST | `/api/v1/auth/login` | Iniciar sesión (token opaco, 72 h) |
| POST | `/api/v1/auth/logout` | Revocar la sesión actual |
| GET | `/api/v1/auth/me` | Perfil |
| GET | `/api/v1/auth/sessions` | Sesiones abiertas |
| GET | `/api/v1/companies` | Buscar empresas por ticker, nombre, sector |
| GET | `/api/v1/companies/{ticker}` | Ficha (descarga si no está en caché) |
| POST | `/api/v1/companies/{ticker}/refresh` | Recalcular y guardar instantánea |
| GET | `/api/v1/companies/{ticker}/analysis` | Métricas, series, escenarios y sensibilidad |
| POST | `/api/v1/companies/{ticker}/valuation` | DCF con supuestos propios |
| GET | `/api/v1/companies/{ticker}/report` | Informe del motor (Markdown) |
| POST | `/api/v1/research` | Encolar investigación (perfil y presupuesto) |
| GET | `/api/v1/research` | Historial de trabajos |
| GET | `/api/v1/research/{id}` | Estado, etapa y pasos |
| POST | `/api/v1/research/{id}/cancel` | Cancelación cooperativa |
| GET | `/api/v1/research/{id}/steps` | Salida de cada rol |
| GET | `/api/v1/research/plan` | Roles, modelos y coste máximo estimado |
| GET | `/api/v1/reports` | Historial paginado |
| GET | `/api/v1/reports/{id}` | Secciones, auditoría y roles |
| GET | `/api/v1/reports/{id}/export?format=md\|csv\|html` | Exportación |
| DELETE | `/api/v1/reports/{id}` | Eliminar informe propio |
| POST/GET | `/api/v1/portfolios` | Crear / listar carteras simuladas |
| GET | `/api/v1/portfolios/{id}` | Posiciones, efectivo y rendimiento |
| POST | `/api/v1/portfolios/{id}/trades` | Compra o venta ficticia |
| GET | `/api/v1/portfolios/{id}/trades` | Historial de operaciones |
| GET | `/api/v1/markets` | Mercados con código MIC |
| GET/POST | `/api/v1/instruments` | Buscar / crear instrumentos multimercado |
| POST/GET | `/api/v1/instruments/{uid}/quotes` | Registrar / consultar cotizaciones propias o globales |
| POST/GET | `/api/v1/fx-rates` | Registrar / consultar tipos de cambio |
| GET/POST | `/api/v1/real/accounts` | Listar / crear cuentas reales |
| GET/PATCH/DELETE | `/api/v1/real/accounts/{id}` | Detalle, edición y borrado |
| GET | `/api/v1/real/accounts/{id}/summary` | Valoración, FIFO/media, XIRR, TWR y distribución |
| GET/POST | `/api/v1/real/accounts/{id}/movements` | Historial / alta manual validada |
| PATCH/DELETE | `/api/v1/real/accounts/{id}/movements/{mid}` | Corrección y borrado con revalidación |
| GET | `/api/v1/real/overview` | Consolidado por moneda base |
| GET | `/api/v1/real/performance` | Rentabilidad de todas las cuentas |
| POST | `/api/v1/real/accounts/{id}/imports/preview` | CSV/XLSX: mapeo, validación y duplicados sin escribir |
| POST | `/api/v1/real/accounts/{id}/imports/{batch}/confirm` | Confirmación explícita (total o parcial) |
| GET/POST | `/api/v1/real/documents` | Listar / subir documentos privados |
| POST | `/api/v1/real/documents/{id}/extract` | OCR local; no registra movimientos |
| POST | `/api/v1/real/documents/{id}/confirm` | Revisión humana y alta del movimiento |
| GET | `/api/v1/real/documents/{id}/file` | Descarga autenticada del original |
| GET/PATCH | `/api/v1/settings` | Preferencias y presupuesto |
| GET | `/api/v1/dashboard` | Resumen del panel |
| GET | `/api/v1/system/logs` | Eventos de auditoría de la cuenta |

## 6. Seguridad

- Contraseñas: PBKDF2-HMAC-SHA256, 260 000 iteraciones, sal de 16 bytes.
- Sesiones: token aleatorio de 256 bits; en la base de datos solo el SHA-256.
  Caducidad configurable y revocación por sesión.
- Enumeración de cuentas: el login verifica un hash ficticio cuando el correo no
  existe, para no filtrar información por tiempo de respuesta.
- Aislamiento: cada consulta filtra por `user_id`; un informe ajeno responde 404.
- Límites: por IP y ruta (ventana de 60 s) y cupo de trabajos por hora.
- Presupuesto: límite por trabajo y límite mensual por usuario.
- Registro de auditoría (`audit_events`) sin datos sensibles.
- Cartera real: cuentas, movimientos, lotes, importaciones y documentos filtran por
  `user_id`. Un recurso ajeno responde 404. Las cotizaciones y tipos manuales llevan
  `user_id`; las globales (proveedor) son las únicas visibles para todos.
- Documentos: validación de firma real (PDF/JPEG/PNG/WebP), límite de tamaño, nombre
  saneado, almacenamiento fuera de `web/dist` y descarga con token. Un documento que
  respalda un movimiento no se puede borrar.
- El service worker **no cachea** `/api`: ni cifras ni tokens quedan en disco.
- `HttpOnly` no aplica (token en `localStorage`); es una decisión consciente para
  una SPA con API propia. Riesgo documentado: un XSS podría leer el token, por eso
  se evita `dangerouslySetInnerHTML` en todo el cliente.

## 7. Interfaz y PWA

- React 18 + TypeScript + Vite + Tailwind, sin librería de componentes externa.
- Rutas protegidas: `/panel`, `/empresas`, `/investigacion`, `/informes`,
  `/cartera-real`, `/cartera`, `/ajustes`; públicas `/` y `/acceder`.
- Cartera real: pestañas de resumen, movimientos, importación y documentos; el dashboard
  muestra el consolidado por divisa y enlaza al desglose.
- Responsive: barra superior en escritorio y navegación inferior en móvil.
- PWA: `manifest.webmanifest`, iconos 192/512/maskable, `sw.js` (shell
  cache-first, navegación network-first, API solo red) y `offline.html`.
- Instalación mediante `beforeinstallprompt`; aviso de conexión y estados de
  sincronización en el propio shell.
- Exportación: Markdown y CSV desde el backend; HTML imprimible para PDF desde el
  navegador (no se genera PDF en el servidor).

## 8. Despliegue

- `Dockerfile` multi-stage: compila la PWA con Node y sirve todo con FastAPI.
- `docker-compose.yml`: API + PostgreSQL 16 + volúmenes de caché y documentos privados.
  La imagen instala `tesseract-ocr` y `tesseract-ocr-spa` para el OCR local.
- Migraciones al arrancar (`alembic upgrade head`), healthcheck real.
- `env.example` lista todas las variables; ninguna clave real está en el repo.
- Costes orientativos (2026): una instancia pequeña (1 vCPU/1 GB) y Postgres
  gestionado básico suelen entrar en planes gratuitos o de ~5–15 USD/mes. El
  coste variable real es la IA: con `gpt-4o-mini`, un informe estándar de cinco
  roles ronda centavos; el presupuesto por trabajo lo acota.

**Límite del hosting gestionado de este workspace:** su builder es solo Node. La
app se despliega como contenedor (Docker) o en un host con Python; el `dist` de la
PWA lo sirve el propio backend, así que no hay que desplegar dos servicios.

## 9. Pruebas

- Suite total: **461 recolectadas, 460 aprobadas, 1 omitida** por depender de red (sin red
  en ninguna prueba de plataforma).
- Cartera real: 10 pruebas numéricas del motor contable y 11 de API (aislamiento,
  importación, documentos, cotizaciones privadas y `as_of`).
- CI: motor (3.10/3.12), Ruff, migraciones (upgrade/check/downgrade), arranque de
  la API y build de la PWA con verificación de artefactos.

## 10. Limitaciones declaradas

1. **Precio de mercado no verificado**: el motor no usa precios de Yahoo para el
   margen de seguridad en esta versión; el campo de precio de la calculadora es
   opcional y lo aporta el usuario.
2. **Sin búsqueda global de tickers**: el explorador busca en empresas ya
   consultadas; cualquier ticker de la SEC se abre manualmente.
3. **Cartera simulada sin benchmark automático**: el precio de las posiciones usa Yahoo
   (fuente no oficial) y el benchmark queda en `null` salvo que se añada la serie.
4. **Cartera real sin proveedor automático de precios/noticias**: la valoración usa
   cotizaciones registradas con fuente y fecha (manuales/importadas). No hay sincronización
   programada ni feeds de noticias, dividendos o calendarios; es la siguiente fase.
5. **OCR condicionado al entorno**: requiere el binario `tesseract-ocr`. En este workspace
   no está instalado, por lo que la ruta se prueba con un extractor simulado; el contenedor
   sí lo instala. Si falta, la API responde 503 y no finge una extracción.
6. **Cola en proceso**: una sola réplica sin Redis. La cartera real no usa la cola; las
   actualizaciones automáticas y alertas aún no están implementadas.
7. **Límite de peticiones en memoria**: válido para una instancia.
8. **Sin pruebas de navegador**: no se añadió Playwright; el frontend se verifica
   con TypeScript y build, no con capturas automatizadas.
9. **Sin APK**: no se generó ni probó Capacitor; la estructura PWA queda lista.
10. **Auditoría numérica heurística**: detecta cifras no rastreables, no errores
    semánticos ni citas falsas de texto.
11. **Datos cualitativos de IA sin acceso a noticias**: los modelos solo ven el
    expediente; si no hay fuente externa, el rol lo declara no disponible.
12. **SQLite no es exacto a nivel de almacenamiento**: los cálculos usan `Decimal` y
    PostgreSQL conserva `Numeric` exacto; en SQLite el valor persistido tiene afinidad
    numérica. Para contabilidad de producción, usar PostgreSQL.
