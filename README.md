# Beta Local - Revision de Planillas EMTP

Aplicacion local para cargar multiples planillas Excel (`.xlsx`) y ejecutar una primera capa de validaciones automatizadas.

## Objetivo

- Recibir planillas tal como llegan desde establecimientos.
- Guardar original sin modificar (con hash SHA256 para trazabilidad).
- Aplicar reglas iniciales de consistencia y campos obligatorios.
- Entregar resumen y observaciones para revision humana.

## Requisitos

- Python 3.11+

## Instalacion

```bash
cd beta_revision_emtp
pip install -r requirements.txt
```

## Ejecucion

```bash
cd beta_revision_emtp
streamlit run app.py
```

Esto abrira una interfaz web en `http://localhost:8501`.

### Opcionalmente: Prueba rápida desde terminal

```bash
cd beta_revision_emtp
python test_validator.py
```

Salida esperada:
```
archivo: <nombre>.xlsx
criticos: N
advertencias: N
info: N
filas_regular: N
filas_innov: N
total_solicitado_estimado: $XXX.XX
```

## Interfaz Web (Streamlit)

1. **Carga de archivos**: Arrastra o selecciona multiples archivos .xlsx.
2. **Configuracion**: 
   - Checkbox para aplicar tope presupuestario (opcional).
   - Input del monto maximo si es aplicable.
3. **Validacion**: Boton "Procesar planillas".
4. **Resultados**:
   - Tabla resumen por archivo (estado, criticos, advertencias, totales).
   - Tabla detallada de observaciones (severidad, regla, hoja, fila, mensaje).
   - Botones de descarga: CSV del resumen y CSV de observaciones.
5. **Almacenamiento**: Original preservado en `data/uploads/` con timestamp + hash.

## Reglas iniciales incluidas (beta v1)

### Estructura de hojas
- `STR-001` - Hoja "Especialidad" ausente.
- `STR-002` - Hoja "Innovacion" ausente.
- `STR-005` (warning) - Hoja "Evaluacion 1" ausente.
- `STR-006` (warning) - Hoja "Evaluacion 2" ausente.
- `STR-003` (warning) - Hoja "Resumen proyecto especialidad" ausente.
- `STR-004` (warning) - Hoja "Propuesta habilitacion" ausente.

### Evaluacion 1
- `EV1-001` (critical) - Recurso ALTERNATIVO incluido sin justificacion pedagogica valida (texto real, no vacio/simbolos).
- `EV1-002` (warning) - No se puede determinar margen de indice de uso (columna "indice X 1,5").
- `EV1-003` (warning) - Cantidad solicitada > 0 con margen de indice invalido (<= 0).
- `EV1-004` (warning) - Cantidad solicitada supera el margen permitido de indice de uso.

### Evaluacion 2 (Innovacion)
- `EV2-001` (critical) - Campo obligatorio vacio o invalido en el bloque de innovacion.
- `EV2-002` (warning) - Tipo de recurso fuera de lista desplegable de innovacion.
- `EV2-003` (warning) - Tipo de innovacion fuera de lista desplegable (Profundizar/Complementar).
- `EV2-004` (critical) - Justificacion de proposito sin texto valido.
- `EV2-005` (warning) - No se observa justificacion explicita de cantidad solicitada.
- `EV2-006` (critical) - Cantidad vacia o <= 0.
- `EV2-007` (critical) - Valor unitario vacio o <= 0.
- `EV2-008` (warning) - Total no coincide con cantidad x valor.

### Especialidad (Decreto N° 240 y Alternativo)
- `ESP-001` (warning) - Fila sin nombre corto del recurso.
- `ESP-002` (warning) - Campo "incluido al proyecto" debe ser SI/NO.
- `ESP-003` (warning) - Si esta incluido, tipo debe ser REGULAR/ALTERNATIVO.
- `ESP-004` (critical) - Recurso ALTERNATIVO sin justificacion pedagogica.
- `ESP-005` (critical) - Recurso incluido con cantidad vacia/<=0.
- `ESP-006` (critical) - Recurso incluido con valor unitario vacio/<=0.
- `ESP-007` (warning) - Valor total != cantidad x valor unitario.
- `ESP-008` (warning) - Cantidad supera indice de uso.
- `ESP-009` (info) - Fila marcada NO incluye pero tiene cantidad >0.

### Innovacion
- `INN-001` (critical) - Campo obligatorio vacio (tipo, nombre, descripcion, OA, tipo_innov, justificacion).
- `INN-002` (warning) - Tipo de innovacion fuera de catalogo (debe ser Profundizar/Complementar).
- `INN-003` (critical) - Cantidad vacia/<=0.
- `INN-004` (critical) - Valor unitario vacio/<=0.
- `INN-005` (warning) - Total no coincide con cantidad x valor.
- `INN-006` (info) - Justificacion corta (<80 caracteres); sugerir revision humana.

### Resumen Proyecto Especialidad
- `RES-001` (critical) - Presupuesto total fuera de rango permitido segun matricula enrolada.
  - Matrículas 10-30: $15M a $60M
  - Matrículas 31-60: $15M a $78M
  - Matrículas 61-90: $15M a $96M
  - Matrículas 91-120: $15M a $114M
  - Matrículas 121-150: $15M a $132M
- `RES-002` (critical) - Presupuesto de HABILITACIÓN supera 10% del total solicitado.
- `RES-003` (warning) - Error al leer hoja Resumen proyecto especialidad.
- `RES-004` (warning) - Diferencia significativa entre matrícula oficial (BBDD) y matrícula actual declarada (>10%).

### Presupuesto
- `BUD-001` (critical) - Total solicitado supera tope presupuestario configurado.

### Sistema
- `SYS-001` (critical) - No se puede leer el archivo Excel.

## Salidas

- **Resumen**: Tabla con estado (OK / REQUIERE REVISION / ERROR), cantidad de hallazgos por severidad, totales estimados por seccion.
- **Observaciones**: Tabla detallada: archivo, severidad, regla ID, hoja, fila, campo, mensaje.
- **CSV Export**: Descargas de ambas tablas.
- **Copia Inmutable**: Cada archivo cargado se preserva en `data/uploads/YYYYMMDD_HHMMSS_<hash12>_<nombre>.xlsx`.

## Workflow

1. Establecimientos envian planillas sin modificar.
2. Coordinador carga multiples archivos en interfaz web.
3. Sistema valida reglas automaticas e inmediatas.
4. Resultado: 
   - Archivos con 0 criticos y pocos warnings → OK para aprobar.
   - Archivos con advertencias → Revision rapida.
   - Archivos con criticos → Devolver a establecimiento.
5. Exportar reportes para auditoría y seguimiento.

## Siguientes pasos

- [ ] Ampliar catalogo de reglas (ej. validacion contra decreto 240 exacto).
- [ ] Agregar integracion con IA (Copilot) para priorizar justificaciones de bajo puntaje.
- [ ] Dashboard de seguimiento (estados pendientes, aprobados, rechazados).
- [ ] API REST para integracion con sistemas del Ministerio.
- [ ] Soporte para carga en lote automatica via carpeta o email.
- [ ] Generacion de reportes ejecutivos en PDF.

## Notas tecnicas

- **Motor**: Pandas para lectura eficiente, custom dataclass para findings.
- **Almacenamiento**: Copias inmutables con timestamp + SHA256.
- **Escalabilidad**: Preparado para procesamiento asincronico escalonado futuro.
- **Confidencialidad**: No edita originales, no envia datos a sistemas externos.


