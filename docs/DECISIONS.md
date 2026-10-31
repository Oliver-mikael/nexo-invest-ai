# DECISIONS — Nexo Invest AI

## Decisiones técnicas

### 1. Construcción desde cero en lugar de reconstrucción a partir de código perdido

Motivo: el repositorio contiene solo README.md y el respaldo solo contiene ese mismo README.md.
No existe código Python anterior recuperable. Construir sobre código inexistente sería falsificar
el estado del proyecto.

Consecuencia: se pierde cualquier avance anterior no recuperado. Se documenta explícitamente.

### 2. pyproject.toml con hatchling, dependencias mínimas y pytest como dev dependency

Motivo: estándar Python actual, interoperable, fácil de reconstruir, compatible con el entorno
disponible (Python 3.10, pip 22.0.2, sin venv).

### 3. Tipos explícitos para dinero y periodos

Motivo: el núcleo del proyecto es calcular correctamente. Money, Period y Frequency hacen
explícitas la moneda, la escala y la frecuencia, y evitan bugs por mezcla implícita de unidades.

### 4. Scale enum para evitar mezcla implícita de unidades

Motivo: auditoría del motor financiero mostró que el código original permitía mezclar escalas
distintas (millones con unidades) sin transformación ni error. Esto produce resultados financieramente
incorrectos. Se introduce Scale enum y conversión explícita to_scale().

Consecuencia: los cálculos ahora exigen por defecto escalas compatibles; se añade flag explícito
same_scale_required=False para casos controlados documentados.

### 5. Validación de escalas en growth_rate y margin

Motivo: el crecimiento interanual y los márgenes comparativos pierden sentido si se mezclan escalas
distintas sin transformación documentada.

Consecuencia: growth_rate y margin devuelven None cuando las escalas no coinciden, salvo flag
explícito. Se añaden pruebas de regresión.

### 6. ROIC documentado como aproximación

Motivo: la implementación actual usa operating_income / invested_capital, sin ajuste por impuestos
ni capital promedio. Se documenta como aproximación en lugar de presentar una fórmula más estricta que
los datos actuales no pueden calcular.

### 7. Periodo anterior documentado como limitación

Motivo: el método _previous_period elige el periodo más reciente estrictamente anterior, no
necesariamente el año fiscal anterior. Sin calendario fiscal explícito, no se puede calcular
crecimiento interanual estricto. Se documenta esta limitación en lugar de forzar un filtro incorrecto.

### 8. FiscalCalendar con regla finish.month <= close_month => finish.year, else finish.year + 1

Motivo: necesidad de identificar año fiscal de forma reproducible y documentada. La regla adoptada
nombra el año fiscal por el año civil del mes de cierre (convención FY = año del cierre).

Consecuencia: esta es una convención, no la única posible. Se documenta explícitamente para evitar
ambigüedad en cálculos futuros.

### 9. TTM como suma de últimos 4 trimestres consecutivos disponibles

Motivo: necesidad de calcular TTM reproducible sobre datos trimestrales consecutivos. Se define
ttm_periods como secuencia estrictamente consecutiva (diferencia 75-120 días entre fin de trimestre
y fin del siguiente) y compute_ttm_from_quarters como suma de los valores correspondientes.

Consecuencia: TTM devuelve None si hay menos de 4 trimestres consecutivos o algún valor ausente.
Se añade esta semántica explícita para evitar calcular TTM sobre periodos no consecutivos.

### 10. Fiscal growth estricto cuando hay calendario fiscal

Motivo: el crecimiento interanual debe poder calcularse sobre el mismo año fiscal anterior cuando
está disponible el calendario fiscal. Se añade revenue_growth_fiscal que usa growth_rate_strict con
el periodo fiscal anterior.

Consecuencia: cuando hay calendario fiscal, revenue_growth se actualiza con el crecimiento fiscal
estricto. Se documenta que sin calendario, revenue_growth compara con el periodo anterior más reciente.

### 11. Periodo duplicado documentado como sobrescritura

Motivo: el diseño actual permite añadir income statement con mismo periodo (misma fecha de fin).
Cuando ocurre, el último sobrescribe al anterior. Se documenta como comportamiento, no como error.

Consecuencia: los usuarios deben evitar duplicados; si los hay, el último escribe. Se añade prueba
de regresión para documentar el comportamiento.

### 12. Núcleo gratuito y reproducible

Motivo: el proyecto prioriza análisis verificable. No se introducen dependencias de pago ni APIs
obligatorias desde el inicio. Las fuentes en línea se añaden como adaptadores opcionales con
fixtures de prueba.

### 13. Fuentes como adaptadores con procedencia

Motivo: distinguir datos observados de estimados y hechos de hipótesis. Una fuente debe poder
rastrearse: identificador, fecha de consulta, método, unidades y hash cuando corresponda.

Consecuencia: se introduce DataSource, Observation, ProvenanceRegistry para que cada dato lleve
procedencia y el informe pueda separar hechos verificados, no verificados, supuestos y estimaciones.

### 14. Modelo de procedencia explícito con validaciones

Motivo: necesidad de construir un informe que distinga datos simulados, manuales y externos,
con estados de verificación y limitaciones documentadas.

Consecuencia:
- DataType distingue tipos de dato (ingresos, balance, flujo de caja, shares, precio, métrica).
- DataOrigin distingue origen: simulated, manual, external_verified, external_unverified.
- VerificationState distingue estado de verificación: unverified, pending, partially_verified, verified.
- DataSource registra fuente con campos requeridos (id, name, entity), propiedades is_verified,
  is_external, is_simulated, is_manual.
- Observation vincula fuente, periodo, métrica, valor, value_origin, verified, raw_value, notes, limitations.
  is_verified requiere verified=True, source.verified y valor presente/no ausente.
- ProvenanceRegistry registra fuentes sin duplicados, observaciones sin duplicados a nivel de
  fuente/métrica/periodo, con quality_report y to_financial_state.
- Validaciones de duplicados, campos requeridos, datos ausentes, escalas/monedas incompatibles.
- Importación circular evitada con importación bajo demanda en to_financial_state.

### 15. Cierre de ciclo de trazabilidad fuente → motor → informe

Motivo: el informe debe poder rastrear cada cifra hasta su fuente, y el motor debe poder ser
construido a partir de registros de procedencia.

Consecuencia:
- FinancialState.from_provenance(registry, metric) construye FinancialState por métrica.
- to_financial_state(registry, metric) delega en from_provenance para evitar importación circular.
- El informe puede integrarse con procedencia para separar hechos verificados, no verificados,
  supuestos y estimaciones.

### 16. Informe Markdown primero, HTML después

Motivo: Markdown es reproducible, versionable y fácil de revisar. El núcleo analítico primero;
la presentación visual después.

### 17. CLI primero, interfaz visual después

Motivo: un CLI funcional es el primer producto útil y estable. La interfaz visual se añade
cuando el núcleo es suficiente.

### 18. Pruebas con datos locales desde el inicio

Motivo: el entorno puede no tener acceso a fuentes financieras en línea. Las pruebas no deben
depender de Internet. Los datos externos se validan aparte y se marcan como verificados solo tras
consulta real.

### 19. Escenarios bajista/base/alcista separados del modelo único

Motivo: una única proyección canónica no transmite la incertidumbre del negocio. Se parametrizan tres escenarios con crecimiento de ingresos, tasa de descuento y crecimiento terminal explícitos y se valida que la tasa de descuento es estrictamente superior al crecimiento terminal en cada escenario.

Consecuencia: se obtienen valores por acción distintos por escenario y se pueden mostrar margen de subida/bajada respecto al precio actual cuando ese precio esté disponible.

### 20. Comparables como modelo explícito con origen documentado

Motivo: los comparables solo tienen valor si se documenta qué se compara y con qué confianza. Se introduce Comparable con métricas comparables (precio, enterprise_value, revenue, ebitda, net_income, net_debt), origen y estado de verificación, y se calculan múltiplos medianos.

Consecuencia: los datos insuficientes o escalas incompatibles devuelven None; los comparables simulados se marcan como tales y el informe lo dice.

### 21. Cierre de Hito E con separación de estados de verificación e integridad del informe

Motivo: el informe debe distinguir hechos verificados, datos no verificados, simulados, supuestos y estimaciones, y debe poder declararse insuficiente sin generar una conclusión de inversión injustificada.

Consecuencia: el informe integra bloques de procedencia, muestra cobertura de datos explícita, incluye condiciones objetivas de descarte y, cuando faltan ingresos o los 4 trimestres consecutivos, informa la incompletitud sin recomendar inversión.

### 22. SEC EDGAR como primera fuente real, con condiciones de acceso respetadas

Motivo: es oficial, pública, gratuita y accesible sin clave. Exige `User-Agent` identificable
con contacto (sin él responde HTTP 403), un límite de peticiones y una huella del contenido.

Consecuencia: el adaptador aplica intervalo mínimo configurable, caché en disco y SHA-256 del
documento; `NEXO_SEC_CONTACT` define el contacto y su ausencia se avisa por stderr.

### 23. Escalera de niveles: descargado, validado y corroborado

Motivo: una descarga correcta no demuestra que una cifra financiera sea correcta. Mezclar ambos
hechos permitiría presentar datos sin contraste como verificados.

Consecuencia: cada observación lleva su nivel. `EXTERNAL_VALIDATED` exige unidades homogéneas,
fechas coherentes e identidad contable cumplida **en ese periodo**; un periodo históricamente
incoherente no invalida los demás pero no se promueve. `EXTERNAL_CORROBORATED` exige una segunda
ruta interna (concepto alternativo o suma de cuatro trimestres reales) y se declara como
corroboración intra-fuente, no como segunda fuente independiente.

### 24. Exclusión explícita de periodos acumulados YTD

Motivo: los 10-Q publican trimestres sueltos y acumulados de 6 y 9 meses. Sumarlos como si fueran
trimestres produciría un TTM financieramente falso (se observó con datos reales).

Consecuencia: solo se aceptan periodos de duración trimestral real (80-100 días) o anual (330-400).
Cuando la fuente no publica el cuarto trimestre como periodo independiente, el TTM es `None` y se
explica; no se completa con la diferencia entre anual y acumulados.

### 25. Selección del periodo anterior por frecuencia y por tipo de estado

Motivo: con datos reales, el periodo anterior se tomaba de la lista global de periodos, que incluye
balances instantáneos etiquetados como anuales. El resultado era comparar el ejercicio anual con el
balance del trimestre cerrado más cercano: crecimiento y dilución quedaban mal o sin calcular.

Consecuencia: la comparación se restringe a estados de resultados de la misma frecuencia. La
dilución, además, no se calcula si no hay dos periodos comparables.

### 26. Deuda total desde componentes, marcada como mínimo si falta alguno

Motivo: muchas empresas no publican `total_debt` pero sí sus componentes. Ignorarlos dejaba la
deuda neta vacía; sumarlos sin más declararlos como deuda total sería engañoso.

Consecuencia: se suman los componentes observados y, si falta alguno, la nota dice que la cifra es
un mínimo. La deuda neta resta caja e inversiones corrientes, y advierte de que no se restan las
inversiones a largo plazo (Apple quedaría con deuda neta sobrestimada).

### 27. FCF estimado cuando la empresa no lo reporta, siempre etiquetado

Motivo: `free_cash_flow` no existe como concepto XBRL estándar único. Dejar `None` impedía valorar;
calcularlo en silencio como si fuera reportado sería peor.

Consecuencia: `free_cash_flow = flujo operativo − |inversiones|` con `free_cash_flow_estimated=True`
y una nota que lo declara. El informe distingue «cifra reportada» de «estimación».

### 28. Sin precio verificado no hay margen de seguridad ni recomendación

Motivo: el objetivo del proyecto es no confundir una valoración atractiva con una señal de compra.

Consecuencia: `can_recommend` es siempre `False`; los criterios miden calidad y endeudamiento, no
precio, y el informe lo dice expresamente. La valoración por escenarios se publica como sensibilidad
a supuestos, nunca como predicción.

### 29. Yahoo Finance como fuente de precios, declarada como no oficial

Motivo: es el endpoint público sin clave que responde en este entorno (Stooq exige superar un reto
JavaScript, comprobado el 2026-10-27). Es suficiente para estudiar una regla, no para decidir.

Consecuencia: toda serie queda en `EXTERNAL_DOWNLOADED`, con la limitación de fuente no oficial
registrada en el registro de procedencia y en el informe de la prueba histórica.

### 30. Parámetros de la prueba histórica fijados antes de ver resultados

Motivo: optimizar la ventana o los costes sobre la propia muestra infla el resultado y convierte una
prueba exploratoria en una promesa imposible de sostener.

Consecuencia: ventana, rebalanceo, comisión y deslizamiento se declaran por defecto, no se ajustan
para mejorar el resultado, y el informe añade las limitaciones (un activo, un periodo, sin corrección
por comparaciones múltiples, sin impuestos ni liquidez real de las órdenes).

## Decisiones documentadas pero no implementadas aún

- Validaciones de consistencia entre estados (ingresos vs flujo de caja, etc.).
- HTML para informes si tiene sentido.
- Ampliar la prueba histórica a varios activos y periodos, con corrección por comparaciones múltiples.

### 31. Comparables como modelo sin múltiplos inventados

Motivo: sin precios ni múltiplos de mercado verificados, calcular múltiplos «de mercado» sería
fabricar datos. El modelo existe, pero no produce valores si los insumos no son reales.

Consecuencia: el informe declara que no hay comparables aplicables en lugar de rellenar la
sección con cifras de ejemplo.

### 32. Estrategia táctica declarada no lista en lugar de aproximada

Motivo: una señal táctica construida sobre precios de una fuente no oficial y con una sola
serie no es defendible. Documentar los requisitos exactos es más útil que publicar señales
débiles con apariencia de rigor.

Consecuencia: `strategies.py` informa del estado `no_lista` con la lista de datos necesarios y
`can_recommend = False` en todos los casos.

### 33. Resultado negativo publicado tal cual

Motivo: la prueba histórica real dio 65,07 % frente a 133,25 % de buy & hold (cifra que,
tras la corrección de la decisión 40, es 132,90 %). Ocultarlo o
ajustar parámetros hasta que ganara sería exactamente el sesgo que el proyecto intenta evitar.

Consecuencia: el informe de la prueba histórica abre con el resultado y cierra afirmando que no
demuestra rentabilidad. Los parámetros no se reajustaron tras ver los resultados.

### 34. Sin automatización persistente declarada falsamente

Motivo: este entorno no tiene demonios ni tareas programadas. Decir que hay una actualización
diaria sería falso.

Consecuencia: `scripts/update_reports.sh` deja registro con fecha, OK o FALLO por paso, y la
documentación indica que debe lanzarlo el programador del sistema del usuario.

### 35. Nasdaq como segunda fuente, declarada como distribución y no como fuente primaria

Motivo: hace falta una segunda fuente gratuita y sin clave que permita comprobar que la
cifra llega intacta desde el documento hasta el informe. Nasdaq la ofrece, pero sus
cifras proceden de los mismos documentos que presenta la empresa.

Consecuencia: la coincidencia sube el dato a `EXTERNAL_CORROBORATED` con la limitación
dichosamente explícita de que se comprueba la cadena de distribución, no una medición
independiente. Presentarlo como una segunda fuente primaria sería engañar sobre el tipo
de garantía que se tiene.

### 36. Relación de unidad inferida, nunca atribuida a la fuente

Motivo: `api.nasdaq.com` devuelve `$416,161,000` sin declarar la unidad; el valor real es
416.161 millones de dólares.

Consecuencia: la alineación se hace con la potencia de diez que mejor ajusta (aquí ×1000)
y se registra como inferida. Si ninguna potencia de diez razonable alinea, el resultado es
discrepancia, no coincidencia: una cifra escurridiza no se convierte en un «aproximado».

### 37. La segunda fuente se registra como fuente, no como observación paralela

Motivo: crear una observación de ingresos del mismo periodo en distinta escala permitiría
que sustituyera a la cifra primaria en el estado financiero (un valor 1000 veces menor
sustituyendo al real).

Consecuencia: se registra el `DataSource` secundario (URL, consulta, hash, límites), el
contraste se conserva en las notas de la observación primaria y solo ésta sube de nivel.
El registro no acepta dos cifras del mismo periodo que no sean comparables por construcción.

### 38. Precio comprobado en dos fuentes con símbolo y fecha obligatorios

Motivo: un precio solo es verificable si es el mismo activo en el mismo día en dos
orígenes independientes. Elegir el día más cercano disfraza un hueco de dato.

Consecuencia: `contrast_close_price` exige fecha exacta en ambas series y símbolo
coincidente; si falta alguno, el resultado es `incomparable` y no se calcula margen de
seguridad. En la sesión comprobada (2026-10-27) ambas fuentes dan 347,10 USD.

### 39. Margen de seguridad con fórmula declarada y negativo explicado

Motivo: la cifra solo es útil si se dice qué mide. `1 − precio / valor por acción` puede
salir negativa cuando el precio supera el valor estimado.

Consecuencia: la fórmula va en el informe, el signo negativo se explica en lugar de
cortarlo, y se declara que no es recomendación de venta. Si falta precio comprobado o el
valor por acción no es positivo, no se calcula.

### 40. Corrección del coste de entrada en la referencia buy & hold

Motivo: la auditoría del Ciclo 3 detectó que el buy & hold se medía desde su primer valor
(que ya incorpora el coste de compra) mientras la estrategia partía del capital inicial
(sin costes pagados todavía). La comparación descontaba los costes solo a una de las dos.

Consecuencia: ambas curvas se miden desde el capital inicial. El buy & hold pasa de
133,25 % a 132,90 % y la conclusión no cambia: la regla (65,07 %) sigue por debajo. Se
añade una prueba que exige que la rentabilidad publicada coincida con el cálculo manual
que sí incluye costes.

### 41. Auditoría con recálculo independiente y control de anticipación

Motivo: afirmar que una prueba histórica no tiene sesgo exige comprobarlo, no declararlo.

Consecuencia: `audit_backtest` recalcula cada cifra publicada con fórmulas escritas aparte
y repite la ejecución sobre la serie recortada a media fecha: si la estrategia leyera el
futuro, las curvas divergirían. Se incluyen controles negativos que demuestran que la
auditoría detecta curvas manipuladas (no es un chequeo decorativo).

### 42. Restricción de acceso observada se documenta en lugar de esconderse

Motivo: `api.nasdaq.com` corta silenciosamente las peticiones cuyo `User-Agent` incluye
una URL de contacto (verificado con peticiones repetidas), mientras que la SEC exige lo
contrario.

Consecuencia: cada adaptador lleva su propio identificador y la restricción queda como
limitación del módulo, no como truco particular del cliente.

Decisiones implementadas en este ciclo (Ciclo 3, 0.3.0):
- Motor de escenarios bajista/base/alcista con supuestos explícitos (ver 19).
- Motor de comparables con selección de pares documentada (ver 20).
- Cierre de Hito E con separación de estados de verificación e integridad del informe (ver 21).
- SEC EDGAR como fuente real con escalera descargado/validado/corroborado (ver 22-24).
- Selección del periodo anterior por frecuencia y deuda total desde componentes (ver 25-26).
- FCF estimado siempre etiquetado (ver 27).
- Sin precio verificado no hay margen de seguridad ni recomendación (ver 28).
- Yahoo Finance declarado no oficial y parámetros del backtest fijados de antemano (ver 29-30).
- 250 pruebas definidas: 249 aprobadas, 1 omitida por requerir red.
- Respaldo verificado: `nexo-invest-ai-backup-2026-10-28.zip`, 42 archivos, `testzip` OK,
  restauración limpia sin discrepancias y suite completa ejecutada desde la copia restaurada.
  SHA-256 en `nexo-invest-ai-backup-2026-10-28.sha256`.

Ciclo 3 (0.3.0): decisiones 35 a 42. 303 pruebas aprobadas, 1 omitida. Informes
`reports/verify-aapl-2026-10-28.md` y `reports/backtest-aapl-2026-10-28.md` reproducidos
byte a byte salvo la línea de fecha.
