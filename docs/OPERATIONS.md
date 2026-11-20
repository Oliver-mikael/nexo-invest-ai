# Operación y preparación de recuperación

Estado: **IMPLEMENTADO** para backup/restore local aislado y para el flujo de backup cifrado
con almacenamiento de directorio local. No hay un proveedor remoto configurado ni una
restauración externa real demostrada.

## Objetivos propuestos

Para una instalación pequeña administrada por una persona:

- RPO inicial: 24 horas.
- RTO inicial: 4 horas.
- Retención local propuesta: 7 diarios, 4 semanales y 3 mensuales.

Son objetivos de diseño, no garantías. El RPO depende de la frecuencia real de ejecución y
de que exista una copia externa. El RTO depende de la disponibilidad de Docker, PostgreSQL,
volúmenes, credenciales y una máquina de sustitución.

## Backup

Ejecutar `scripts/backup_compose.sh` con Docker Compose activo:

```bash
NEXO_BACKUP_DIR=/ruta/persistente/backups bash scripts/backup_compose.sh
```

La API se pausa durante la captura. El resultado contiene:

- `postgres.dump`: dump PostgreSQL 16 en formato custom.
- `documents.tar.gz`: documentos privados.
- `metadata.env`: formato e identidad de la base.
- `SHA256SUMS`: integridad SHA-256.

La captura confirma la integridad antes de publicar el directorio final. Un fallo deja limpia
la carpeta temporal. La restauración exige comprobar primero el SHA-256 y nunca reemplaza
una instalación existente.

## Restauración

```bash
bash scripts/restore_compose.sh /ruta/al/backup
```

La restauración crea un proyecto Compose aislado, nuevo, sin puertos publicados. Comprueba
checksum, metadatos, rutas seguras, esquema Alembic, archivos, registros documentales y
contenidos SHA-256. Conserva el resultado en `RESTORE_RESULT.txt`.

## Backup cifrado y almacenamiento

`scripts/external_backup.py` cifra el conjunto de backup **antes de copiarlo** mediante
AES-256-GCM (cifrado autenticado). El encabezado identifica el formato; la clave de 32 bytes
se obtiene de `NEXO_BACKUP_ENCRYPTION_KEY`, codificada en Base64, nunca de argumentos de
línea de comandos. Las sumas SHA-256 del backup original se verifican antes del cifrado y el
SHA-256 del objeto cifrado se comprueba después de copiarlo. El tag GCM detecta cambios y
claves incorrectas al descifrar.

La implementación `LocalDirectoryStore` es una simulación local de la interfaz de
almacenamiento: **no es almacenamiento externo ni tolera la pérdida de este host**.
No se ha configurado cuenta, credencial o destino de terceros. La clave debe generarse y
custodiarse fuera del repositorio y del servidor de aplicación, con una copia de recuperación
independiente. Perderla impide restaurar los backups. La rotación exige conservar las claves
anteriores hasta vencer todos los backups cifrados con ellas; la versión actual usa una clave
configurada única y no incluye un llavero multi-clave.

Ejemplo para publicar un backup local ya generado:

```bash
export NEXO_BACKUP_DIR=/ruta/local/backups
export NEXO_EXTERNAL_BACKUP_DIR=/ruta/de/prueba/almacen-cifrado
export NEXO_BACKUP_RETENTION_DAYS=30
export NEXO_BACKUP_ENCRYPTION_KEY='<base64 de una clave aleatoria de 32 bytes>'
python3 scripts/external_backup.py run
```

`run` ejecuta primero `scripts/backup_compose.sh`, luego cifra y copia el resultado. Para
publicar una copia ya generada: `python3 scripts/external_backup.py publish DIRECTORIO`.
La restauración por identificador es `python3 scripts/external_backup.py restore
IDENTIFICADOR`; descifra en un directorio temporal con permisos restringidos y llama al
restaurador aislado existente. La limpieza temporal ocurre también ante fallo. El destino de
`NEXO_EXTERNAL_BACKUP_DIR` debe ser un directorio autorizado; al montarlo sobre un disco
distinto puede servir para probar el transporte, pero no equivale a un proveedor remoto.

Retención configurable: `NEXO_BACKUP_RETENTION_DAYS` (30 días por defecto, mínimo 1). Solo
elimina objetos cifrados que coincidan con el formato de identificador de esta herramienta.
`operations.jsonl` registra hora, acción, resultado, duración, tamaño, checksum y código de
error; nunca registra claves, tokens, nombres de usuario, consultas ni contenido de documentos.

### Proveedores y costes

Solo el backend de directorio local está implementado y probado automáticamente. La interfaz
es deliberadamente pequeña para permitir adaptadores, pero los proveedores siguientes son
**compatibles como opciones de diseño, no conectores implementados ni probados**:

| Opción | Coste relativo | Ventaja | Limitación / trabajo pendiente |
| --- | --- | --- | --- |
| AWS S3, Google Cloud Storage, Azure Blob | Pago según región, capacidad, operaciones y egreso | Durabilidad y controles de acceso gestionados | Hace falta adaptar autenticación, permisos, lifecycle y recuperación |
| Backblaze B2 / Wasabi | Normalmente orientados a bajo coste por GB; confirmar tarifas vigentes | Alternativas de objeto con API S3 en algunos planes | Costes de descarga, mínimos, límites y residencia varían |
| S3 compatible autogestionado (p. ej. MinIO) | Infraestructura y operación propias | Control de datos y pruebas sin dependencia de un SaaS | No protege ante pérdida del host/sitio si comparte infraestructura |
| SFTP / almacenamiento montado | Coste del servidor o disco | Sencillo, portable y fácil de probar | Operación, capacidad, permisos y resiliencia son responsabilidad propia |

No se publican precios numéricos porque dependen de volumen, región, retención, solicitudes,
egreso, impuestos y cambios de tarifa. Antes de seleccionar proveedor deben estimarse esos
factores, residencia de datos, cifrado en reposo, bloqueo de borrado, MFA y recuperación de
credenciales. Ninguna transferencia debe activarse sin autorización explícita.

## Monitorización y alertas

`python3 scripts/monitor.py` comprueba API `/api/v1/health`, disponibilidad de PostgreSQL
desde Compose, último backup (por defecto no más antiguo de 24 horas), espacio libre,
marcadores críticos de logs de los últimos 5 minutos y último resultado de restauración.
Emite JSON con estados y detalles sanitizados, sin volcar líneas de log ni secretos. Códigos
de salida: `0` saludable, `1` comprobación degradada, `2` umbral/configuración inválida.

Umbrales configurables: `NEXO_HEALTH_URL`, `NEXO_BACKUP_MAX_AGE_HOURS`,
`NEXO_MIN_FREE_STORAGE_MB`, `NEXO_BACKUP_LOG`. Se recomienda programar esta comprobación
cada minuto con el supervisor del host; el repositorio no instala un cron ni garantiza que
se ejecute.

Una alerta webhook opcional puede habilitarse con `NEXO_ALERT_WEBHOOK_URL`; transmite solo
estado y nombres de comprobaciones fallidas, no paths, datos de cuentas ni contenido de logs.
La URL es un secreto y debe inyectarse desde el gestor de secretos del operador. No se ha
configurado ni probado un destino externo. La función de entrega devuelve `failed` sin
imprimir la URL si el endpoint no responde.

La monitorización identifica fallos desde el momento en que corre; no es un servicio
gestionado ni alerta si el propio host o el scheduler dejan de funcionar. Se requiere un
monitor externo autorizado para vigilar la disponibilidad del host y del proceso de monitoreo.

## RPO/RTO y evidencia

RPO 24 h y RTO 4 h son objetivos iniciales, no garantías. No hay backup programado en el
repositorio: para aproximar RPO ≤24 h se requiere completar y verificar backups con una
frecuencia máxima de 24 h, monitorizar la última ejecución, tener capacidad y credenciales
accesibles, y mantener una copia fuera del host. El RPO medido en una prueba se calcula como
tiempo desde el último backup verificado hasta el fallo simulado; los registros deben tener
reloj UTC sincronizado.

El RTO debe medirse desde la decisión de recuperación hasta que PostgreSQL, documentos y API
estén verificados y disponibles en infraestructura de sustitución. Incluye aprovisionamiento,
descarga, descifrado, migraciones, validación y DNS/red. Una restauración en contenedores
locales solo mide el tramo técnico de datos; no garantiza RTO de servicio.

### Medición local desechable (2026-11-19)

`bash scripts/test_compose_recovery.sh` ejecutó PostgreSQL 16 y el almacén cifrado de
directorio local en proyectos Docker temporales. Antes del backup se insertó un marcador
controlado y, justo después de verificar la copia, otro marcador; la recuperación conservó
el primero y perdió exactamente **1 registro de prueba posterior al backup**. En la última
repetición, RPO observado: **0,184 s** entre el fin del backup verificado y el fallo simulado.
Restaurar, descifrar, verificar la base y comprobar los documentos tomó **8,175 s**; el
registro interno de `external_backup.py` midió **7,550 s** hasta que terminó el restaurador.
Los contenedores e imágenes ya estaban disponibles localmente.

Resultado: los objetivos de 24 h y 4 h son holgados para ese ensayo aislado, pero esto no es
una medida de ejecución programada, descarga de proveedor, aprovisionamiento de un servidor
nuevo, inicio de API, DNS, ni carga de producción. No permite inferir capacidad, rendimiento
ni una garantía de RPO/RTO en producción. La recuperación PostgreSQL y documentos se verificó
en un segundo proyecto local, no en un host independiente.

Para aceptar cada objetivo operativamente: asignar responsables y suplentes, custodiar clave
y credenciales fuera del host, monitorizar espacio y backups, disponer de Docker/imagen y
red, documentar accesos, practicar una restauración en una máquina distinta y conservar
mediciones con artefactos desechables. No subir datos financieros reales durante pruebas.

## Responsabilidades

Antes de producción, el operador debe asignar:

- responsable de ejecutar la copia;
- custodio de la clave de cifrado;
- custodio de credenciales;
- responsable de revisar fallos;
- responsable de restauraciones;
- frecuencia de restauración de prueba;
- retención y autorización de datos financieros;
- procedimiento de alta y baja de responsables.
