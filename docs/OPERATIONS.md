# Operación y preparación de recuperación

Estado: **IMPLEMENTADO** para backup/restore local aislado. Las copias externas y las
alertas de disponibilidad requieren infraestructura y autorización.

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

## Copia externa

No se configurará ningún proveedor externo, cuenta, credencial o transferencia automática
sin autorización. Estrategia recomendada:

1. Generar el backup y verificarlo localmente.
2. Cifrar el directorio completo antes de transmitirlo con GPG, age o una herramienta
   equivalente.
3. Transmitir únicamente mediante una interfaz desacoplada del repositorio, por ejemplo
   `rclone crypt`, `rsync` sobre SSH o el almacenamiento cifrado de un proveedor.
4. Registrar hora, destino, tamaño, checksum y resultado sin guardar contraseñas o tokens.
5. Probar periódicamente la descarga y restauración del cifrado en un entorno desechable.

La clave de cifrado debe ser independiente de los secretos de aplicación, conservarse fuera
del servidor y contar con custodios definidos por el operador. Las claves de acceso no deben
guardar ni registrarse en el repositorio.

## Monitorización mínima

El endpoint `/api/v1/health` informa del estado de la API y una consulta `SELECT 1` a
PostgreSQL. Las comprobaciones previstas para una instalación pequeña son:

- disponibilidad del endpoint cada minuto;
- disponibilidad de PostgreSQL desde Compose;
- existencia y edad del último backup;
- resultado de la última comprobación SHA-256;
- éxito o fallo del último restore aislado;
- espacio disponible en los volúmenes y directorio de backups;
- errores críticos registrados por el servicio.

Las alertas externas son opcionales. Pueden usar correo SMTP, Uptime Kuma o un script con
webhook propio sin registrar secretos en el repositorio. No se consideran implementadas hasta
tener infraestructura y una prueba real.

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
