# ordenar_fotos

Herramienta de línea de comandos (Windows) para **ordenar, deduplicar y respaldar
bibliotecas grandes de fotos y videos** usando la **fecha de captura real** leída
de los metadatos EXIF/QuickTime — no las fechas del sistema de archivos, que se
arruinan cada vez que movés o copiás archivos.

Diseñada para carpetas desordenadas de decenas de GB, con archivos repartidos en
carpetas cuyo nombre no corresponde al contenido, fechas cruzadas y duplicados
generados por intentos previos de ordenamiento.

**Principio rector:** el origen NUNCA se modifica en modo copia (que es el
predeterminado), y absolutamente ningún script borra archivos sin confirmación
explícita tuya.

---

## Índice

1. [Características](#1-características)
2. [Cómo funciona por dentro](#2-cómo-funciona-por-dentro)
3. [Requisitos](#3-requisitos)
4. [Instalación](#4-instalación)
5. [Estructura del proyecto](#5-estructura-del-proyecto)
6. [Flujo de trabajo recomendado](#6-flujo-de-trabajo-recomendado)
7. [Uso detallado de cada script](#7-uso-detallado-de-cada-script)
   - [7.1 auditoria.py](#71-auditoriapy--auditoría-de-solo-lectura)
   - [7.2 organizar.py](#72-organizarpy--ordenamiento-por-añoymes)
   - [7.3 unificar.py](#73-unificarpy--consolidación-en-carpeta-plana)
   - [7.4 registro.py](#74-registropy--registro-de-respaldo-con-hash)
   - [7.5 importar.py](#75-importarpy--importación-incremental)
   - [7.6 dedup.py](#76-deduppy--deduplicación-final)
8. [Cadena de prioridad de fechas](#8-cadena-de-prioridad-de-fechas)
9. [Garantías de seguridad](#9-garantías-de-seguridad)
10. [Privacidad: qué no se sube a GitHub](#10-privacidad-qué-no-se-sube-a-github)
11. [Solución de problemas](#11-solución-de-problemas)
12. [Licencia](#12-licencia)

---

## 1. Características

- **Ordena por fecha de captura real** (EXIF/QuickTime) en carpetas `Año\Mes`.
- **No depende de las fechas del sistema de archivos** (que se corrompen al copiar/mover).
- **Modo copia estricto por defecto**: tu biblioteca original queda intacta.
- **Auditoría previa de solo lectura** con reportes antes de tocar nada.
- **Detección de duplicados** por hash MD5 (muestra rápida y confirmación total).
- **Registro de respaldo** con hash de cada archivo, para importar solo lo nuevo.
- **Trazabilidad completa**: cada operación queda registrada en CSV.
- **Reanudable**: si se interrumpe, re-ejecutás y continúa donde quedó.
- **Sin dependencias de Python**: solo biblioteca estándar (Python 3.10+).
- **ExifTool incluido**: no hace falta instalar nada más.

---

## 2. Cómo funciona por dentro

Entender este flujo te permite interpretar cada reporte y cada columna de los CSV
que generan los scripts.

### 2.1 Recorrido y filtrado

1. El script recorre **recursivamente** la carpeta `--origen` con `os.walk`.
2. Descarta subcarpetas que no debe tocar: si el destino o la propia carpeta del
   proyecto están dentro del origen, se **podan del recorrido** (nunca se
   procesan a sí mismas).
3. Filtra por **extensión multimedia** (JPG, PNG, HEIC, RAW de varias marcas,
   MP4, MOV, AVI, MKV, 3GP… — la lista completa está en
   `src/exif_utils.py`, constantes `EXT_IMAGENES` y `EXT_VIDEOS`). Con
   `--extensiones` podés reducir ese conjunto según lo que indique tu auditoría.
4. Para cada archivo que pasa el filtro se lee su **tamaño**; ese tamaño es la
   primera clave para detectar duplicados (dos archivos con distinto tamaño no
   pueden ser idénticos).

### 2.2 Lectura de metadatos en lote con ExifTool

En vez de lanzar ExifTool una vez por archivo (miles de procesos, muy lento), se
lo invoca **una sola vez por lote de 200 archivos** en modo JSON:

```
exiftool.exe -j -G -n -EXIF:DateTimeOriginal -EXIF:DateTimeDigitized ... lote_de_200_archivos
```

- **Por qué 200:** Windows tiene un límite de ~32.767 caracteres por línea de
  comandos; con lotes de 200 rutas largas jamás se supera.
- **`-G`** prefixa cada etiqueta con su grupo (`EXIF:`, `QuickTime:`, `File:`),
  lo que permite comparar prioridades sin ambigüedad.
- Si un lote falla parcialmente, ExifTool igual emite el JSON de los archivos
  que sí pudo leer; el script lo aprovecha en lugar de abortar.
- El resultado se guarda en un diccionario `{ruta_normalizada: {tag: valor}}`.
  Como ExifTool puede reemplazar caracteres no ASCII por `?` en Windows, la
  búsqueda posterior tolera eso: si la ruta exacta no está, se empareja por
  **(nombre de archivo + tamaño)**, que es inmune a ese problema.

### 2.3 Selección de la fecha

Para cada archivo se aplica la **cadena de prioridad** (sección 8): se toma la
primera fecha disponible, se **normaliza** a `AAAA-MM-DD HH:MM:SS` (acepta
`2023:06:15 14:30:22`, variantes con guiones, con zona horaria, o solo fecha) y
se valida (mes 1-12, día 1-31, hora ≤ 23...). Si la fecha no es plausible
(ej. mes `13`), se descarta y se sigue con la siguiente fuente.

Esa fecha determina la carpeta de destino: `destino\AAAA\MM\`. Si no hay ninguna
fecha, el archivo cae en `destino\sin_fecha\`.

### 2.4 Copia y resolución de colisiones

Antes de copiar, se decide el nombre final:

1. Si **no existe** un archivo con ese nombre en la carpeta destino → se copia
   con el nombre original.
2. Si **existe y el contenido es idéntico** (mismo tamaño + mismo MD5) → se
   **omite**: ya está respaldado (estado `omitido-ya-existente`). No gasta
   espacio duplicado.
3. Si **existe pero el contenido es distinto** → se prueba `nombre_1.ext`,
   `nombre_2.ext`... hasta encontrar un hueco. **Jamás se sobrescribe nada.**

En `unificar.py` e `importar.py` la copia es **verificada**: se copia a un
archivo temporal, se recalcula tamaño + MD5 del destino y se compara con el
origen; recién entonces se renombra al definitivo. Si la verificación falla, el
temporal se borra y el archivo queda registrado como `error` (nunca se queda una
copia corrupta silenciosamente).

### 2.5 Deduplicación

- **Detección rápida** (`auditoria.py`): agrupa por `(tamaño, hash de muestra)`,
  donde la muestra son 16 KB del inicio + medio + final del archivo. Barato de
  calcular; sirve para *candidatos*.
- **Confirmación total** (`dedup.py`, `unificar.py`): MD5 del archivo completo.
  Solo entonces se afirma que dos archivos son idénticos.

### 2.6 Trazabilidad y reanudación

Cada acción queda escrita en un CSV de `logs\` con su **estado** (ver el
significado de cada estado en la sección 11). Esos CSV son además la base de la
**reanudación**: al re-ejecutar un script, las rutas ya procesadas con éxito se
leen del CSV y se **omite** — por eso podés cortar una ejecución de 50 GB y
volver a lanzarla sin repetir trabajo.

### 2.7 Registro e importación incremental (el "cerebro" del respaldo)

1. `registro.py` hashea (MD5 completo) cada archivo de la carpeta de respaldo y
   lo anota en `registro\respaldo.csv` → tenés un inventario verificable de lo
   que ya tenés.
2. `importar.py` hashea cada archivo de una carpeta nueva y lo compara contra
   ese CSV por **(tamaño + MD5)**: si el contenido ya está registrado **no lo
   copia aunque tenga otro nombre**; si es nuevo, lo copia, verifica y agrega su
   fila al registro para las próximas importaciones.

---

## 3. Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10/11 (PowerShell o CMD) |
| Python | 3.10 o superior — verificar con `python --version` |
| ExifTool | **Ya incluido** en el repositorio (`exiftool.exe` + `exiftool_files/`) |
| Espacio en disco | Para modo copia: espacio libre igual al tamaño de la biblioteca |

> Si no tenés Python: descargalo de https://www.python.org/ y marcá la casilla
> **"Add Python to PATH"** durante la instalación.

---

## 4. Instalación

```powershell
# 1) Clonar el repositorio
git clone https://github.com/ProyectosCzh/DocsOrganizator.git
cd DocsOrganizator

# 2) Verificar que Python y ExifTool responden
python --version
.\exiftool.exe -ver
#    → debe imprimir la versión (p. ej. 13.59)

# 3) Verificar que los scripts arrancan
python src\auditoria.py --help
```

No hay `pip install`: el proyecto usa únicamente la biblioteca estándar de Python.

**Sobre ExifTool:** el ejecutable y sus módulos (`exiftool_files/`) ya vienen en
la raíz del proyecto, listos para usar. Si querés actualizarlo o cambiarlo,
descargá la versión oficial desde **https://exiftool.org/** y reemplazá
`exiftool.exe` + `exiftool_files/` (los scripts también detectan un
`exiftool.exe` presente en el `PATH` del sistema).

---

## 5. Estructura del proyecto

```
ordenar_fotos/
├── README.md               ← este documento (guía completa)
├── LICENSE                 ← licencia MIT del código + nota de ExifTool
├── .gitignore              ← excluye datos privados y salidas
│
├── exiftool.exe            ← motor de metadatos (incluido)
├── exiftool_files/         ← módulos de ExifTool + sus licencias (incluidos)
│
├── src/
│   ├── exif_utils.py       ← biblioteca compartida (fechas, hashes, ExifTool)
│   ├── auditoria.py        ← FASE 1: auditoría de solo lectura
│   ├── organizar.py        ← FASE 2: ordena por Año\Mes (copia)
│   ├── unificar.py         ← consolida en carpeta plana sin duplicados
│   ├── registro.py         ← registro de respaldo con hash MD5
│   ├── importar.py         ← importación incremental (solo lo nuevo)
│   └── dedup.py            ← FASE 3: deduplicación final (opcional)
│
├── logs/                   ← LO CREA EN EJECUCIÓN (ignorado por git)
├── reportes/               ← LO CREA EN EJECUCIÓN (ignorado por git)
└── registro/               ← LO CREA EN EJECUCIÓN (ignorado por git)
```

---

## 6. Flujo de trabajo recomendado

```
                    ┌──────────────────────────────┐
   biblioteca       │ 1) auditoria.py  (solo lee)  │──► reportes\
   desordenada ────►│                              │
                    └──────────────────────────────┘
                                   │  revisás los reportes y decidís
                                   ▼
                    ┌──────────────────────────────┐
                    │ 2) organizar.py  (copia)     │──► destino\YYYY\MM\
                    │    o unificar.py (copia)     │──► destino\ (plana)
                    └──────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ 3) registro.py  (hashea)     │──► registro\respaldo.csv
                    └──────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ 4) importar.py (opcional)    │  importa carpetas nuevas
                    │    solo copia lo que falta   │  SIN repetir contenido
                    └──────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ 5) dedup.py  (opcional)      │  duplicados finales
                    └──────────────────────────────┘
```

---

## 7. Uso detallado de cada script

> Todos los comandos se ejecutan desde la **raíz del proyecto**.
> Entre comillas van tus rutas reales; usá comillas cuando tengan espacios.

### 7.1 `auditoria.py` — Auditoría de solo lectura

Escanea la carpeta origen y genera reportes **sin modificar, mover ni eliminar
nada**. Hacé esto siempre primero.

```powershell
# Uso mínimo
python src\auditoria.py --origen "D:\Fotos Desordenadas"

# Especificar dónde guardar los reportes (opcional)
python src\auditoria.py --origen "D:\Fotos Desordenadas" --salida "E:\Mis Reportes"
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--origen` | Sí | Carpeta raíz a analizar (recursivo, solo lectura) |
| `--salida` | No | Carpeta de reportes. Por defecto: `reportes\` en la raíz del proyecto |

**Reportes generados en `reportes\`:**

| Archivo | Contenido |
|---|---|
| `reporte_extensiones.txt` | Inventario por extensión: nº de archivos, tamaño, % |
| `reporte_fechas.txt` | Cuántos tienen fecha EXIF/QuickTime/nombre/sin fecha + histograma por año |
| `metadatos.csv` | Por archivo: ruta, extensión, tamaño, fecha hallada, fuente de la fecha |
| `duplicados_candidatos.csv` | Posibles duplicados (mismo tamaño + hash de muestra) |
| `muestra_sin_fecha.txt` | Ejemplos de archivos sin fecha detectable |

**Qué decidir después de leer los reportes:** qué extensiones incluir en la
fase siguiente (`--extensiones`), cuántos archivos caerán en `sin_fecha`, y si
hay suficientes duplicados como para justificar `dedup.py`.

---

### 7.2 `organizar.py` — Ordenamiento por Año\Mes

Copia cada archivo multimedia a `destino\YYYY\MM\` según su fecha de captura
real. **El origen queda intacto.**

```powershell
# Copia por defecto → destino\ en la raíz del proyecto
python src\organizar.py --origen "D:\Fotos Desordenadas"

# Copiar a un destino propio (recomendado para discos con espacio)
python src\organizar.py --origen "D:\Fotos Desordenadas" --destino "E:\Fotos_Ordenadas"

# Solo ciertas extensiones (resultado de tu auditoría)
python src\organizar.py --origen "D:\Fotos Desordenadas" --destino "E:\Fotos_Ordenadas" --extensiones jpg,jpeg,png,mp4

# Modo MOVER: libera espacio en el origen (pide confirmación interactiva)
python src\organizar.py --origen "D:\Fotos Desordenadas" --destino "E:\Fotos_Ordenadas" --modo mover
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--origen` | Sí | Carpeta raíz con los archivos desordenados |
| `--destino` | No | Por defecto: `destino\` en la raíz del proyecto |
| `--modo` | No | `copiar` (defecto) o `mover` — `mover` pide confirmación `s/N` |
| `--extensiones` | No | Lista separada por comas, p. ej. `jpg,mp4`. Por defecto: todas las multimedia |

**Resultado:**

```
destino\
├── 2011\01\IMG_1234.jpg
├── 2013\07\DSC0001.JPG
├── ...
└── sin_fecha\archivo_sin_metadatos.jpg
```

**Salidas en `logs\`:**

| Archivo | Contenido |
|---|---|
| `ordenacion.csv` | ruta origen → ruta destino → fecha usada → fuente → estado |
| `resumen_ordenacion.txt` | Totales por estado y por fuente de fecha |
| `errores.txt` | Archivos que fallaron (permisos, en uso, corruptos) |

**Reglas:** conserva el nombre original; si hay colisión de nombres agrega
`_1`, `_2`... (jamás sobrescribe); si el contenido ya existe, lo omite.

---

### 7.3 `unificar.py` — Consolidación en carpeta plana

Alternativa a `organizar.py`: junta todo en **una sola carpeta plana** sin
duplicados (conserva UNA copia de cada contenido único, decidida por heurística
de nombre: prefiere nombres con fecha parseable, más descriptivos y más cercanos
a la raíz).

```powershell
# Copia a unificadas\ (en la raíz del proyecto)
python src\unificar.py --origen "D:\Fotos Desordenadas" --destino "E:\General"

# Incluir también archivos NO multimedia (pdf, zip, txt...)
python src\unificar.py --origen "D:\Fotos Desordenadas" --destino "E:\General" --todas

# Modo MOVER (pide confirmación; --yes la omite para uso no interactivo)
python src\unificar.py --origen "D:\Fotos Desordenadas" --destino "E:\General" --modo mover

# Sin verificar hash post-copia (más rápido, menos seguro)
python src\unificar.py --origen "D:\Fotos Desordenadas" --destino "E:\General" --sin-verificar
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--origen` | Sí | Carpeta raíz con los archivos (solo lectura en modo copiar) |
| `--destino` | No | Por defecto: `unificadas\` en la raíz del proyecto |
| `--duplicados` | No | Para `--modo mover`. Por defecto: `duplicados\` en la raíz |
| `--modo` | No | `copiar` (defecto) o `mover` |
| `--todas` | No | Incluir todos los archivos, no solo multimedia |
| `--sin-verificar` | No | Omitir la verificación MD5 post-copia |
| `--yes` | No | No pedir confirmación en modo mover |

**Optimización:** primero agrupa por tamaño y solo hashea los archivos que
comparten tamaño con otro (los únicos que pueden ser duplicados). **Reanudable:**
el progreso queda en `logs\unificacion.csv`; al re-ejecutar omite lo ya
procesado y limpia temporales huérfanos (`.tmp_*`).

---

### 7.4 `registro.py` — Registro de respaldo con hash

Genera (o actualiza) el CSV con el **hash MD5 de cada archivo** de una carpeta.
Es la base para saber qué ya tenés respaldado y para que `importar.py` no
repita contenido.

```powershell
# Crear/actualizar el registro de una carpeta (agrega faltantes, no borra filas)
python src\registro.py --carpeta "E:\Fotos_Ordenadas"

# Rehacer el registro desde cero
python src\registro.py --carpeta "E:\Fotos_Ordenadas" --modo reconstruir

# Solo verificar el CSV existente contra la carpeta (no hashea nada)
python src\registro.py --carpeta "E:\Fotos_Ordenadas" --verificar
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--carpeta` | **Sí** | Carpeta a inventariar (solo lectura) |
| `--salida` | No | CSV de salida. Por defecto: `registro\respaldo.csv` |
| `--modo` | No | `actualizar` (defecto, incremental) o `reconstruir` (desde cero) |
| `--verificar` | No | Compara el CSV con la carpeta sin hashear de nuevo |

> **Nota:** analiza los archivos del **nivel superior** de la carpeta (no es
> recursivo). Pensado para la carpeta *plana* del respaldo: si querés registrar
> una biblioteca ya ordenada en `Año\Mes`, usá `unificar.py` o registrá la
> carpeta plana resultante.

**Salidas en `registro\`:** `respaldo.csv` (nombre, tamaño, md5, fecha
modificación, origen), `resumen.txt`, `errores.txt`.

> **Sugerencia:** guardá una copia de `registro\respaldo.csv` en otro disco:
> es tu inventario verificable de respaldos.

---

### 7.5 `importar.py` — Importación incremental

Compara carpetas nuevas contra el registro por **(tamaño + MD5)** y copia solo
lo que todavía no tenés, aunque tenga otro nombre.

```powershell
# SIMULACIÓN: informa qué copiaría, sin copiar nada (hacé esto primero)
python src\importar.py --origen "D:\Fotos Nuevas" --carpeta-destino "E:\Fotos_Ordenadas" --simular

# Importar de verdad
python src\importar.py --origen "D:\Fotos Nuevas" --carpeta-destino "E:\Fotos_Ordenadas"

# Varias carpetas origen a la vez (repetir --origen)
python src\importar.py --origen "D:\Fotos Nuevas 1" --origen "D:\Fotos Nuevas 2" --carpeta-destino "E:\Fotos_Ordenadas"

# Solo ciertas extensiones
python src\importar.py --origen "D:\Fotos Nuevas" --carpeta-destino "E:\Fotos_Ordenadas" --extensiones jpg,mp4
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--origen` | Sí (repetible) | Carpeta(s) a importar; podés repetir el flag |
| `--carpeta-destino` | **Sí** | Carpeta destino del respaldo |
| `--registro` | No | Por defecto: `registro\respaldo.csv` |
| `--simular` | No | Solo informa; no copia ni escribe el registro |
| `--extensiones` | No | Filtro, p. ej. `jpg,mp4` |

**Salidas en `logs\`:** `importacion.csv` (reanudable),
`resumen_importacion.txt`, `errores_importacion.txt`.

Cada copia se **verifica** (tamaño + MD5) antes de registrarse: si la
verificación falla, borra la copia dañada y la marca como error.

> Ejecutá `registro.py` al menos una vez antes de importar; con el registro
> vacío se copiaría todo (el propio script te avisa con un `AVISO`).

---

### 7.6 `dedup.py` — Deduplicación final

Confirma duplicados con **hash MD5 completo** y, opcionalmente, mueve las copias
redundantes a `duplicados\`. **Nunca borra.**

```powershell
# Solo reportar (no mueve nada)
python src\dedup.py --carpeta "E:\Fotos_Ordenadas\destino"

# Mover copias redundantes a duplicados\ (preserva estructura relativa)
python src\dedup.py --carpeta "E:\Fotos_Ordenadas\destino" --mover

# Cambiar la carpeta de salidas
python src\dedup.py --carpeta "E:\Fotos_Ordenadas\destino" --salida "E:\Reportes Dup"
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `--carpeta` | Sí | Carpeta a analizar (típicamente el destino ya ordenado) |
| `--mover` | No | Mover redundantes a `duplicados\` dentro de la carpeta analizada |
| `--salida` | No | Por defecto: `logs\` en la raíz del proyecto |

**Salidas en `logs\`:** `duplicados_confirmados.csv` (marca `conservar` /
`redundante` por archivo), `resumen_duplicados.txt`.

---

## 8. Cadena de prioridad de fechas

Para cada archivo, se elige la **primera fecha disponible** en este orden:

| # | Fuente | Origen | Confianza |
|---|---|---|---|
| 1 | `EXIF:DateTimeOriginal` | Fecha de disparo de la cámara | ✅ Alta |
| 2 | `EXIF:DateTimeDigitized` / `EXIF:CreateDate` | EXIF | ✅ Alta |
| 3 | `QuickTime:CreationDate` / `CreateDate` (+ variantes) | Videos MP4/MOV/M4V | ✅ Alta |
| 4 | `RIFF:DateTimeOriginal` / `DateCreated` | AVI/WAV | ✅ Alta |
| 5 | Patrón de fecha en el nombre (`IMG_20230615_143022`, `2023-10-25`, timestamp Unix...) | Nombre del archivo | ⚠️ Media |
| 6 | `File:FileModifyDate` | Sistema de archivos | ⚠️ **Dudosa** (va marcada en el log) |
| 7 | Ninguna | — | ➜ carpeta `sin_fecha\` |

Cada fila del CSV de logs indica **qué fuente se usó**, para que puedas revisar
los dudosos.

---

## 9. Garantías de seguridad

| Garantía | Detalle |
|---|---|
| Origen intacto | En modo `copiar` (defecto) nada se mueve ni elimina del origen |
| Auditoría inofensiva | `auditoria.py` es 100% solo lectura |
| Sin sobrescrituras | Colisión de nombre → sufijo `_1`, `_2`...; colisión de contenido → se omite |
| Sin borrados automáticos | Ningún script borra sin que ustedes lo confirmen (`--modo mover` pide `s/N`) |
| Verificación post-copia | `unificar.py` e `importar.py` comparan tamaño + MD5 tras copiar |
| Trazabilidad | Cada acción queda en CSV: origen → destino → fecha → fuente → estado |
| Reanudable | Podés interrumpir y re-ejecutar: lo ya hecho se omite |
| Protección contra rutas cruzadas | `organizar.py` y `unificar.py` se niegan a ejecutar si el destino está dentro del origen (o al revés) |

---

## 10. Privacidad: qué no se sube a GitHub

Los reportes y logs contienen **rutas reales de tus fotos**, nombres de
archivos y carpetas privadas, y hashes. Por eso el `.gitignore` excluye
permanentemente:

```
logs/  reportes/  registro/     ← salidas con tus rutas y hashes
destino/  unificadas/  duplicados/  ← tus fotos ordenadas
.venv/  __pycache__/            ← entorno Python
```

Nada de eso puede entrar a un commit con un `git add .` normal. Si algún día
querés publicar un reporte de ejemplo, revisalo a mano antes: los CSV contienen
rutas completas.

> **Consejo:** los archivos `.csv` que generan estos scripts son para uso
> personal; no los adjuntes a issues ni los compartas sin sanitizar.

---

## 11. Solución de problemas

### Errores frecuentes

| Problema | Solución |
|---|---|
| `ERROR: no se encontró exiftool.exe` | Verificá que `exiftool.exe` y `exiftool_files\` estén en la raíz del proyecto, o que `exiftool` esté en el PATH. Probá `.\exiftool.exe -ver` |
| `python` no se reconoce | Reinstalá Python marcando **Add to PATH**, o usá `py` en lugar de `python` |
| `ERROR: la carpeta destino está DENTRO de la carpeta origen` | Elegí un destino fuera del origen (otra carpeta o disco); es una proteccion para que no se copien a sí mismos |
| `Acceso denegado` / archivo en uso | Cerrá el visor de fotos que esté usando el archivo; queda en `errores.txt` y no detiene el proceso |
| Espacio insuficiente | Apuntá `--destino` a otro disco, o usá `--modo mover` (con confirmación) |
| Comandos largos con espacios | Usá siempre comillas dobles alrededor de las rutas |

### Casos que no son errores

| Síntoma | Qué significa |
|---|---|
| Muchos archivos en `sin_fecha` | Formatos sin metadatos (WhatsApp, capturas, escaneos). Mirá `reporte_fechas.txt`; revisá esa carpeta manualmente |
| Años absurdos en el histograma (p. ej. 1324) | Cámaras/relojes con fecha mal configurada o EXIF inválido. Se ven en `reporte_fechas.txt` |
| Fecha marcada como `filesystem-dudosa` | No había metadatos ni fecha en el nombre: se usó la fecha del archivo, poco confiable. Revisalos en `ordenacion.csv` |
| `AVISO: el registro esta vacio` | Todavía no corriste `registro.py`; sin registro, `importar.py` copiaría todo |

### Significado de cada estado en los CSV

| Estado | Dónde aparece | Significado |
|---|---|---|
| `copiado` | `ordenacion.csv`, `unificacion.csv`, `importacion.csv` | Se creó la copia en el destino |
| `movido` | `ordenacion.csv` | Se movió desde el origen (modo `--modo mover`) |
| `omitido-ya-existente` | `ordenacion.csv` | Ya había un archivo con el mismo nombre **y** el mismo contenido en el destino |
| `ya-existente` | `unificacion.csv` | Mismo caso, en `unificar.py` |
| `duplicado-omitido` | `unificacion.csv` | Era duplicado de otro archivo ya conservado; no se copió (modo copiar) |
| `duplicado-movido` | `unificacion.csv` | Era duplicado; se movió a `duplicados\` (modo mover) |
| `ya-procesado` | `importacion.csv`, `unificacion.csv` | Ya figuraba en el log de una corrida anterior → reanudación |
| `conservar` / `redundante` | `duplicados_confirmados.csv` | De un grupo de idénticos: uno se conserva, los demás son prescindibles |
| `filesystem-dudosa` (columna *fuente*) | `ordenacion.csv` | La fecha usada vino del sistema de archivos: revisar |
| `error` | todos los CSV | Falló la copia/verificación; el detalle está en `errores.txt` |

---

## 12. Licencia

**Código de este proyecto:** [MIT](LICENSE) — libre para usar, modificar y
redistribuir, con la condición de conservar el aviso de copyright.

**ExifTool** (`exiftool.exe` + `exiftool_files/`) es un componente de terceros
de **Phil Harvey**, bajo licencia **GPL / Artistic License** (doble licencia),
y **no** está cubierto por la licencia MIT de arriba.

- Sitio oficial y descargas: **https://exiftool.org/**
- Texto de la licencia: `exiftool_files/LICENSE`
- Licencias de los módulos de Perl incluidos: `exiftool_files/Licenses_Strawberry_Perl.zip`
- Para actualizar: descargá la versión nueva desde https://exiftool.org/ y
  reemplazá `exiftool.exe` + `exiftool_files/`.
