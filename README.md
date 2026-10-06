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
2. [Requisitos](#2-requisitos)
3. [Instalación](#3-instalación)
4. [Estructura del proyecto](#4-estructura-del-proyecto)
5. [Flujo de trabajo recomendado](#5-flujo-de-trabajo-recomendado)
6. [Uso detallado de cada script](#6-uso-detallado-de-cada-script)
   - [6.1 auditoria.py](#61-auditoriapy--auditoría-de-solo-lectura)
   - [6.2 organizar.py](#62-organizarpy--ordenamiento-por-añoymes)
   - [6.3 unificar.py](#63-unificarpy--consolidación-en-carpeta-plana)
   - [6.4 registro.py](#64-registropy--registro-de-respaldo-con-hash)
   - [6.5 importar.py](#65-importarpy--importación-incremental)
   - [6.6 dedup.py](#66-deduppy--deduplicación-final)
7. [Cadena de prioridad de fechas](#7-cadena-de-prioridad-de-fechas)
8. [Garantías de seguridad](#8-garantías-de-seguridad)
9. [Privacidad: qué no se sube a GitHub](#9-privacidad-qué-no-se-sube-a-github)
10. [Solución de problemas](#10-solución-de-problemas)
11. [Licencia y créditos](#11-licencia-y-créditos)

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

## 2. Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10/11 (PowerShell o CMD) |
| Python | 3.10 o superior — verificar con `python --version` |
| ExifTool | **Ya incluido** en el repositorio (`exiftool.exe` + `exiftool_files/`) |
| Espacio en disco | Para modo copia: espacio libre igual al tamaño de la biblioteca |

> Si no tenés Python: descargalo de https://www.python.org/ y marcá la casilla
> **"Add Python to PATH"** durante la instalación.

---

## 3. Instalación

```powershell
# 1) Clonar el repositorio
git clone https://github.com/TU_USUARIO/ordenar_fotos.git
cd ordenar_fotos

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

## 4. Estructura del proyecto

```
ordenar_fotos/
├── README.md               ← este documento
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
├── docs/
│   └── PLAN_DETALLADO.md   ← diseño técnico completo de la herramienta
│
├── logs/                   ← LO CREA EN EJECUCIÓN (ignorado por git)
├── reportes/               ← LO CREA EN EJECUCIÓN (ignorado por git)
└── registro/               ← LO CREA EN EJECUCIÓN (ignorado por git)
```

---

## 5. Flujo de trabajo recomendado

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

## 6. Uso detallado de cada script

> Todos los comandos se ejecutan desde la **raíz del proyecto**.
> Entre comillas van tus rutas reales; usá comillas cuando tengan espacios.

### 6.1 `auditoria.py` — Auditoría de solo lectura

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

### 6.2 `organizar.py` — Ordenamiento por Año\Mes

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

### 6.3 `unificar.py` — Consolidación en carpeta plana

Alternativa a `organizar.py`: junta todo en **una sola carpeta plana** sin
duplicados (conserva UNA copia de cada contenido único, decidida por heurística
de nombre).

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

**Reanudable:** el progreso queda en `logs\unificacion.csv`; al re-ejecutar
omite lo ya procesado. Verificación post-copia: tamaño + MD5.

---

### 6.4 `registro.py` — Registro de respaldo con hash

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

### 6.5 `importar.py` — Importación incremental

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
> vacío se copiaría todo.

---

### 6.6 `dedup.py` — Deduplicación final

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

## 7. Cadena de prioridad de fechas

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

## 8. Garantías de seguridad

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

## 9. Privacidad: qué no se sube a GitHub

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

## 10. Solución de problemas

| Problema | Solución |
|---|---|
| `ERROR: no se encontró exiftool.exe` | Verificá que `exiftool.exe` y `exiftool_files\` estén en la raíz del proyecto, o que `exiftool` esté en el PATH. Probá `.\exiftool.exe -ver` |
| `python` no se reconoce | Reinstalá Python marcando **Add to PATH**, o usá `py` en lugar de `python` |
| Muchos archivos en `sin_fecha` | Son formatos sin metadatos (WhatsApp, capturas, escaneos). Mirá `reporte_fechas.txt`; el patrón de nombre es el respaldo y la carpeta `sin_fecha\` queda para revisión manual |
| Años absurdos en el histograma (p. ej. 1324) | Cámaras/relojes con la fecha mal configurada o fechas inválidas en EXIF. Se detectan en `reporte_fechas.txt`; se pueden corregir después con ExifTool |
| Fecha marcada como `filesystem-dudosa` | No había metadatos ni fecha en el nombre: se usó la fecha del archivo, que es poco confiable. Revisá esos casos en `ordenacion.csv` |
| `Acceso denegado` / archivo en uso | Cerrá el visor de fotos/copias que esté usando el archivo; queda registrado en `errores.txt` y no detiene el proceso |
| Espacio insuficiente | Apuntá `--destino` a otro disco, o usá `--modo mover` (con confirmación) |
| Comandos largos con espacios | Usá siempre comillas dobles alrededor de las rutas |

---

## 11. Licencia y créditos

- **Código de este proyecto:** MIT — ver [LICENSE](LICENSE).
- **ExifTool** (`exiftool.exe` + `exiftool_files/`) es de **Phil Harvey**,
  licencia **GPL / Artistic License**. Sitio oficial y descargas:
  **https://exiftool.org/**
  - Texto de la licencia: `exiftool_files/LICENSE`
  - Licencias de los módulos de Perl incluidos: `exiftool_files/Licenses_Strawberry_Perl.zip`
  - Para actualizarlo: descargá la versión nueva desde exiftool.org y
    reemplazá `exiftool.exe` + `exiftool_files/`.

El diseño técnico completo está en [docs/PLAN_DETALLADO.md](docs/PLAN_DETALLADO.md).
