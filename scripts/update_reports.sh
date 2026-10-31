#!/bin/sh
# Actualización reproducible de los informes de Nexo Invest AI.
#
# Este entorno NO tiene programación persistente de tareas: no hay demonio ni
# servicio que ejecute esto solo. El script está pensado para lanzarse a mano o
# desde el programador del sistema del usuario (cron, systemd timer, Programador
# de tareas). Cada paso registra éxito o fallo en reports/update-log.txt.
#
# Uso:  sh scripts/update_reports.sh
#
# Variables opcionales:
#   NEXO_SEC_CONTACT   contacto con correo real que la SEC exige en el User-Agent.

set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT" || exit 1

LOG="reports/update-log.txt"
mkdir -p reports
STAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[$STAMP] inicio de la actualización" >> "$LOG"

run_step() {
    name=$1
    shift
    if "$@" >> "$LOG" 2>&1; then
        echo "[$STAMP] OK    $name" >> "$LOG"
    else
        echo "[$STAMP] FALLO $name (detalle en las líneas anteriores)" >> "$LOG"
    fi
}

run_step "pruebas" python3 -m pytest -q
run_step "informe AAPL (SEC EDGAR)" python3 -m nexo_invest.cli sec-report \
    --ticker AAPL --out reports/aapl-sec.md --cache-dir .cache/sec
run_step "cribado de estrategia de valor" python3 -m nexo_invest.cli screen \
    --tickers AAPL,MSFT,KO,JNJ --out reports/estrategias.md --cache-dir .cache/sec
run_step "prueba histórica AAPL (precios)" python3 -m nexo_invest.cli backtest \
    --symbol AAPL --out reports/backtest-aapl.md --cache-dir .cache/prices
run_step "verificación con segunda fuente (AAPL)" python3 -m nexo_invest.cli verify \
    --ticker AAPL --out reports/verify-aapl.md --cache-dir .cache/sec \
    --backtest-fixture tests/fixtures/yahoo_aapl_5y.json

echo "[$STAMP] fin de la actualización" >> "$LOG"
echo "Registro: $LOG"
