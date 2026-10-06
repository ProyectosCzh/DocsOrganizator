# Plan Detallado: Ordenamiento de Biblioteca de Fotos y Videos (~50 GB) por Fecha de Creación

**Fecha del documento:** 22 de septiembre de 2026
**Autor:** Asistente de automatización (big-pickle)
**Estado:** Implementado — ver README.md para el uso actual

---

## 1. Objetivo

Procesar una biblioteca de aproximadamente **50 GB de imágenes y videos** (incluyendo formatos antiguos) que actualmente se encuentra desordenada, con:

- Archivos repartidos en carpetas cuyos nombres **no corresponden al contenido**.
- **Fechas de archivo cruzadas/alteradas** (la fecha de modificación y creación del sistema de archivos no es confiable, porque los archivos fueron movidos, copiados y re-procesados en intentos previos de ordenamiento).
- **Duplicados** generados por esos intentos previos.

El objetivo es **reconstruir el orden real por fecha de captura/origen** de cada archivo, agrupándolos en carpetas `Año/Mes`, **sin modificar los archivos originales** (modo copia) y **sin depender de las fechas del sistema de archivos** (que están corrompidas).

**Fuente de verdad:** los metadatos incrustados dentro de cada archivo (EXIF para fotos, QuickTime/otros para videos), que sobreviven a los movimientos y copias.

---

## 2. Problema y por qué la fecha de archivo no sirve

| Fuente de fecha | ¿Confiable? | Motivo |
|---|---|---|
| Fecha de modificación del archivo (filesystem) | ❌ NO | Se actualiza al mover, copiar, editar o re-procesar. Es la causa de las "fechas cruzadas". |
| Fecha de creación del archivo (filesystem) | ❌ NO | Se pierde o cambia al copiar entre discos/carpetas. |
| **EXIF `DateTimeOriginal`** (fotos) | ✅ SÍ | La escribe la cámara al disparar. Viaja incrustada dentro del archivo. |
| **EXIF `DateTimeDigitized` / `CreateDate`** (fotos) | ✅ SÍ | Fechas de captura/digitalización incrustadas. |
| **QuickTime `CreationDate` / `CreateDate`** (videos MP4/MOV/M4V) | ✅ SÍ | Fecha de grabación incrustada en el contenedor del video. |
| Patrón de fecha en el nombre (`IMG_20230615_143022.jpg`) | ⚠️ Parcial | Útil como respaldo cuando no hay metadatos (WhatsApp, redes sociales, capturas). |
| Fecha de archivo (filesystem) | ⚠️ Último recurso | Solo si no existe ninguna de las anteriores; se marca como **dudosa** en el log. |

**Conclusión:** el ordenamiento se basará en los **metadatos incrustados**, con una cadena de prioridad bien definida y trazable (cada archivo registra de dónde salió su fecha).

---

## 3. Tecnologías elegidas y justificación

### 3.1 ExifTool (Phil Harvey) — motor de lectura de metadatos
- **Qué es:** el estándar de facto mundial para leer/escribir metadatos en archivos multimedia. Escrito en Perl, distribuido como ejecutable para Windows sin instalación.
- **Por qué:** soporta cientos de formatos, incluidos los antiguos (JPEG, TIFF, PNG, HEIC/HEIF, CR2/CR3, NEF, ARW, DNG, MP4, MOV, AVI, MKV, etc.). Extrae `DateTimeOriginal`, `CreateDate`, `DateTimeDigitized`, QuickTime `CreationDate`, etc.
- **Modo lote (`-stay_open`)**: un solo proceso persistente procesa miles de archivos sin reiniciar, lo que lo hace rápido incluso en hardware modesto.
- **Licencia:** gratuita (GPL/Artistic), uso personal y comercial permitido.

### 3.2 Python 3 — orquestador
- **Por qué Python y no C++ o JavaScript:**
  - **C++:** máximo rendimiento bruto, pero el cuello de botella real es la lectura de metadatos (que ya resuelve ExifTool). Escribir el parser de EXIF/QuickTime a mano en C++ sería meses de trabajo y errores. No aporta ventaja.
  - **JavaScript/Node:** ecosistema de metadatos multimedia pobre para formatos antiguos; requiere dependencias nativas frágiles en Windows. No aporta ventaja.
  - **Python:** biblioteca estándar suficiente (os, pathlib, csv, json, hashlib, subprocess), sintaxis clara, fácil de auditar y modificar, y se integra perfectamente con ExifTool vía subproceso en modo lote. El rendimiento es más que suficiente: la operación dominante es I/O de disco (copiar 50 GB), no CPU.
- **Versión:** Python 3.10+ (se usará solo la biblioteca estándar; sin dependencias de terceros para minimizar instalación).

### 3.3 PowerShell / CMD — ejecución
- Los scripts se ejecutan desde PowerShell 5.1 (ya disponible en Windows 10/11) o CMD. No se requiere instalación adicional.

### 3.4 ¿Por qué no una herramienta GUI ya hecha?
Se evaluaron (Graphical Photo Organizer, AmoK Exif Sorter, FolioSort, exif-sorter, DigiKam) y se descartaron para este caso porque el usuario requiere:
1. **Auditoría previa de solo lectura** con reporte detallado (las GUI no la ofrecen).
2. **Modo copia estricto** con trazabilidad completa (log CSV por archivo).
3. **Control total** sobre la cadena de prioridad de fechas y el manejo de dudosos/sin fecha.
4. **Deduplicación opcional** posterior con hash.

---

## 4. Arquitectura de la solución

```
ordenar_fotos\
│
├── README.md                  ← guía de uso completa
├── LICENSE                    ← licencia MIT (el código propio)
├── .gitignore                 ← excluye salidas con datos privados
│
├── exiftool.exe               ← motor de metadatos (incluido; fuente: exiftool.org)
├── exiftool_files\            ← módulos de ExifTool + licencias
│
├── src\
│   ├── exif_utils.py          ← biblioteca compartida (fechas, hashes, ExifTool)
│   ├── auditoria.py           ← FASE 1: solo lectura, genera reportes
│   ├── organizar.py           ← FASE 2: copia y ordena por Año/Mes
│   ├── unificar.py            ← alternativa: consolidación en carpeta plana
│   ├── registro.py            ← registro de respaldo con hash MD5
│   ├── importar.py            ← importación incremental (solo lo nuevo)
│   └── dedup.py               ← FASE 3 (opcional): detección de duplicados
│
├── docs\
│   └── PLAN_DETALLADO.md      ← este documento
│
├── reportes\                  ← salidas de la auditoría (CSV/TXT, ignorado por git)
├── registro\                  ← registro de respaldo (ignorado por git)
├── destino\                   ← estructura ordenada Año/Mes (se crea en Fase 2)
└── logs\                      ← logs de ejecución (CSV, ignorado por git)
```

### Flujo de datos

```
Carpeta origen (50 GB, desordenada)
        │
        ▼
[FASE 1] auditoria.py  ──►  reportes\ (extensiones, fechas, duplicados)
        │  (solo lectura, no modifica nada)
        ▼
[FASE 2] organizar.py  ──►  destino\YYYY\MM\archivo.ext  (copia, origen intacto)
        │  + logs\ordenacion.csv (trazabilidad completa)
        ▼
[FASE 3] dedup.py (opcional)  ──►  destino\duplicados\ (confirmados por hash)
```

---

## 5. Fase 1 — Auditoría (`auditoria.py`)

**Naturaleza:** 100% solo lectura. No mueve, copia, renombra ni elimina nada.

### 5.1 Qué hace
1. **Recorrido recursivo** de la carpeta origen.
2. **Inventario por extensión:** conteo de archivos y suma de tamaños por extensión (JPG, JPEG, PNG, GIF, BMP, TIFF, TIF, WEBP, HEIC, HEIF, AVIF, CR2, CR3, NEF, ARW, DNG, MP4, MOV, AVI, MKV, M4V, 3GP, y "otros").
3. **Extracción de fechas en lote** con ExifTool (`-stay_open`, salida JSON): para cada archivo lee `DateTimeOriginal`, `DateTimeDigitized`, `CreateDate`, `ModifyDate` (EXIF) y `CreationDate`, `CreateDate` (QuickTime), más `FileModifyDate` (solo como referencia).
4. **Clasificación por disponibilidad de fecha:**
   - Con fecha real de captura (EXIF/QuickTime) → cuántos y qué años abarcan.
   - Sin metadatos pero con fecha en el nombre → cuántos.
   - Sin nada → cuántos (candidatos a `sin_fecha`).
5. **Distribución por año:** histograma de cuántos archivos caen en cada año (estima cuántas carpetas `Año/Mes` se crearán).
6. **Detección preliminar de duplicados:** agrupa por tamaño de archivo + hash rápido de muestra (16 KB al inicio, medio y final). No elimina nada; solo reporta candidatos.
7. **Muestreo:** lista de 20 archivos de ejemplo por categoría (con fecha / sin fecha / dudosos) para inspección manual.

### 5.2 Salidas (en `reportes\`)
| Archivo | Contenido |
|---|---|
| `reporte_extensiones.txt` | Tabla: extensión → nº archivos → tamaño total → % del total |
| `reporte_fechas.txt` | Resumen: cuántos con fecha EXIF/QuickTime, cuántos por nombre, cuántos sin fecha, histograma por año |
| `metadatos.csv` | Por archivo: ruta, fecha hallada, fuente de la fecha (EXIF/QuickTime/nombre/archivo/dudosa) |
| `duplicados_candidatos.csv` | Grupos de archivos con mismo tamaño y hash de muestra |
| `muestra_sin_fecha.txt` | Ejemplos de archivos sin fecha detectable |

### 5.3 Criterio de decisión tras la auditoría
Con el reporte se decide:
- Qué extensiones incluir en la Fase 2 (p. ej., excluir "otros" no multimedia).
- Cuántos archivos quedarán en `sin_fecha` y si conviene revisarlos manualmente.
- Si la cantidad de duplicados candidatos justifica la Fase 3.

---

## 6. Fase 2 — Ordenamiento (`organizar.py`)

**Naturaleza:** modo **copia**. Los archivos originales NO se tocan; se crea una estructura nueva en `destino\`.

### 6.1 Cadena de prioridad de fecha (por archivo)
1. `EXIF:DateTimeOriginal` — fecha de disparo de la cámara (la más confiable).
2. `EXIF:DateTimeDigitized` — fecha de digitalización.
3. `EXIF:CreateDate` — fecha de creación según EXIF.
4. `QuickTime:CreationDate` — videos MP4/MOV/M4V (con zona horaria).
5. `QuickTime:CreateDate` — videos (respaldo).
6. **Patrón en el nombre de archivo** — `IMG_20230615_143022`, `2023-10-25`, `2023_10_25`, `VID_...` (respaldo para archivos de WhatsApp/redes que pierden metadatos).
7. **Fecha de archivo (filesystem)** — último recurso; el archivo se marca como **dudoso** en el log.
8. **Sin fecha** → carpeta `destino\sin_fecha\`.

### 6.2 Estructura de destino
```
destino\
├── 2005\
│   ├── 01\
│   ├── 02\
│   └── ...
├── 2006\
│   └── ...
├── ...
├── 2026\
│   └── ...
└── sin_fecha\
    └── (archivos sin fecha detectable)
```

### 6.3 Reglas de copia
- Se conserva el **nombre original** del archivo.
- **Colisión de nombres** (dos archivos distintos con el mismo nombre en la misma carpeta): se añade sufijo `_1`, `_2`, ... (nunca se sobrescribe).
- **Colisión por contenido** (mismo nombre y mismo hash): se omite la copia y se registra como duplicado (no se duplica espacio).
- Archivos con fecha **dudosa** (filesystem) se copian igual pero quedan marcados en el log para revisión.
- **Barra de progreso** con conteo (procesados / copiados / omitidos / errores).
- **Procesamiento en lote** de ExifTool: se leen las fechas de todos los archivos en pocas llamadas (no una por archivo).

### 6.4 Salidas (en `logs\`)
| Archivo | Contenido |
|---|---|
| `ordenacion.csv` | ruta origen → ruta destino → fecha usada → fuente de la fecha (EXIF/QuickTime/nombre/filesystem-dudosa) → estado (copiado/omitido/error) |
| `resumen_ordenacion.txt` | Totales: copiados, dudosos, sin fecha, duplicados omitidos, errores |
| `errores.txt` | Archivos que fallaron (permisos, archivo en uso, metadatos corruptos) |

### 6.5 Verificación posterior (manual, sugerida)
- Revisar `resumen_ordenacion.txt` y una muestra de carpetas `Año/Mes`.
- Comprobar que el conteo de archivos en `destino\` coincide con el inventario de la Fase 1 (menos duplicados omitidos).

---

## 7. Fase 3 — Deduplicación y limpieza (opcional, posterior)

Solo después de que el usuario verifique la Fase 2:

1. **`dedup.py`**: confirma duplicados reales con **hash completo (MD5/SHA-1)** de los candidatos de la Fase 1. Mueve/copia las copias redundantes a `destino\duplicados\` (nunca borra automáticamente).
2. **Conversión a modo mover** (opcional): una vez verificado todo, se puede ejecutar `organizar.py --modo mover` para liberar los 50 GB del origen. Se recomienda conservar el origen hasta confirmar integridad.
3. **Limpieza de carpetas vacías** del origen (opcional, solo con confirmación explícita).

---

## 8. Seguridad y garantías

| Garantía | Detalle |
|---|---|
| Origen intacto | La Fase 2 solo copia; nada se mueve ni elimina del origen. |
| Auditoría inofensiva | La Fase 1 es de solo lectura (abre archivos para leer metadatos y muestras de hash; no escribe en ellos). |
| Sin sobrescrituras | Colisiones de nombre se resuelven con sufijos; colisiones de contenido se omiten. |
| Trazabilidad | Cada acción queda en CSV (origen → destino → fecha → fuente). |
| Sin borrados automáticos | Ningún script elimina archivos sin confirmación explícita del usuario. |
| Reanudable | Si se interrumpe, se puede re-ejecutar: los archivos ya copiados se detectan y se omiten. |

---

## 9. Requisitos de instalación (una sola vez)

1. **Python 3.10+** — verificar con `python --version` (si no está, descargar de python.org marcando "Add to PATH").
2. **ExifTool para Windows** — ya incluido en el repositorio (`exiftool.exe` + `exiftool_files\`, fuente: https://exiftool.org/). Para actualizar: descargar la versión nueva desde exiftool.org y reemplazar ambos.
3. **Espacio en disco** — la Fase 2 (copia) requiere ~50 GB libres adicionales (o el tamaño real del lote según la auditoría). Si no hay espacio, se puede apuntar `destino\` a otro disco.

---

## 10. Plan de ejecución paso a paso

| Paso | Acción | Comando/Herramienta | Resultado |
|---|---|---|---|
| 0 | Crear carpeta del proyecto | (ya hecho) | `ordenar_fotos\` con este documento |
| 1 | Instalar Python 3.10+ | python.org | `python --version` funciona |
| 2 | ExifTool | ya incluido en el repo (exiftool.org) | `.\exiftool.exe -ver` funciona |
| 3 | Ejecutar auditoría | `python src\auditoria.py --origen "C:\ruta\a\tus\fotos"` | Reportes en `reportes\` |
| 4 | Revisar reportes | lectura manual | Decisión de extensiones y expectativas |
| 5 | Ejecutar ordenamiento (copia) | `python src\organizar.py --origen "..." --destino "D:\Fotos_Ordenadas"` | Estructura `Año/Mes` + logs |
| 6 | Verificar | revisar logs y carpetas | Conteos coherentes |
| 7 | (Opcional) Deduplicar | `python src\dedup.py --carpeta "..."` | `duplicados\` separados |
| 8 | (Opcional) Mover y liberar espacio | `organizar.py --modo mover` | Origen liberado tras confirmación |

---

## 11. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Archivos sin metadatos (WhatsApp, capturas, escaneos) | Cadena de prioridad con patrón de nombre; carpeta `sin_fecha`; revisión manual con el reporte. |
| Fechas EXIF incorrectas (cámaras con reloj mal configurado) | Se detectan en la auditoría (histograma por año); se pueden corregir después con ExifTool si el usuario lo decide. |
| Videos antiguos sin metadatos de fecha | Se usa patrón de nombre o filesystem marcado como dudoso. |
| Falta de espacio para la copia | `destino\` en otro disco; o pasar a modo mover con confirmación. |
| Archivos corruptos o en uso | Se registran en `errores.txt` y no detienen el proceso. |
| Duplicados que consumen espacio | Fase 3 con hash completo, sin borrado automático. |

---

## 12. Entregables finales

1. `auditoria.py` — script de reconocimiento (solo lectura).
2. `organizar.py` — script de copia y ordenamiento por `Año/Mes`.
3. `dedup.py` — script opcional de deduplicación.
4. `reportes\` — informes de la auditoría.
5. `destino\` — biblioteca ordenada por fecha de captura.
6. `logs\` — trazabilidad completa de cada operación.