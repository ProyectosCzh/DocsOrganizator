# -*- coding: utf-8 -*-
"""
exif_utils.py — Utilidades compartidas para los scripts de ordenamiento.

Funciones:
  - find_exiftool()          : localiza exiftool.exe (junto al script, en la
                                raíz del proyecto o en PATH)
  - read_dates_batch()       : lee fechas de muchos archivos con ExifTool en lotes
  - parse_filename_date()    : extrae fecha desde el nombre del archivo
  - pick_date()              : elige la mejor fecha según la cadena de prioridad
  - hash_muestra()           : hash rápido de muestra (inicio/medio/fin)
  - hash_completo()          : hash MD5 completo del archivo

Uso: solo biblioteca estándar de Python. No requiere instalación de paquetes.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Raíz del proyecto: la carpeta que contiene src/, exiftool.exe, README, etc.
# Todas las salidas por defecto (logs/, reportes/, registro/, destino/) se
# generan AQUÍ, nunca dentro de src/.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Extensiones multimedia reconocidas
# ---------------------------------------------------------------------------
EXT_IMAGENES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".avif", ".jfif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raw",
    ".sr2", ".pef", ".x3f", ".nrw",
}
EXT_VIDEOS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".3gp", ".3g2", ".mpg", ".mpeg", ".mts", ".m2ts", ".ts", ".vob", ".ogv",
    ".ext",
}
EXT_MULTIMEDIA = EXT_IMAGENES | EXT_VIDEOS

# ---------------------------------------------------------------------------
# Etiquetas de fecha que ExifTool debe extraer (con prefijo de grupo)
# ---------------------------------------------------------------------------
TAGS_FECHA = [
    "-EXIF:DateTimeOriginal",
    "-EXIF:DateTimeDigitized",
    "-EXIF:CreateDate",
    "-EXIF:ModifyDate",
    "-QuickTime:CreationDate",
    "-QuickTime:CreateDate",
    "-QuickTime:MediaCreateDate",
    "-QuickTime:TrackCreateDate",
    "-QuickTime:ContentCreateDate",
    "-RIFF:DateTimeOriginal",
    "-RIFF:DateCreated",
    "-File:FileModifyDate",
    "-File:FileCreateDate",
    "-File:FileSize",
]

# Orden de prioridad para elegir la fecha de captura (la confiable primero)
PRIORIDAD_METADATA = [
    "EXIF:DateTimeOriginal",      # 1. fecha de disparo de la cámara
    "EXIF:DateTimeDigitized",     # 2. fecha de digitalización
    "EXIF:CreateDate",            # 3. fecha de creación EXIF
    "QuickTime:CreationDate",     # 4. videos MP4/MOV/M4V (con zona horaria)
    "QuickTime:CreateDate",       # 5. videos (respaldo)
    "QuickTime:MediaCreateDate",  # 6. videos (respaldo)
    "QuickTime:TrackCreateDate",  # 7. videos (respaldo)
    "QuickTime:ContentCreateDate",# 8. videos (respaldo)
    "RIFF:DateTimeOriginal",      # 9. AVI/WAV
    "RIFF:DateCreated",           # 10. AVI/WAV
]

# ---------------------------------------------------------------------------
# Localización de ExifTool
# ---------------------------------------------------------------------------
def configurar_consola():
    """Configura la salida de consola en UTF-8 (evita caracteres raros en Windows)."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def find_exiftool():
    """Busca exiftool.exe: junto al script, en la raíz del proyecto o en PATH.

    El proyecto incluye exiftool.exe (+ exiftool_files/) en su raíz; si se
    distribuye otra versión con otro nombre, también se acepta exiftool(-k).exe.
    """
    script_dir = Path(__file__).resolve().parent

    # Búsqueda recursiva: primero en src/, luego en la raíz del proyecto
    # (por si el ejecutable quedó en otra subcarpeta)
    for base in (script_dir, PROJECT_ROOT):
        for candidato in base.rglob("exiftool.exe"):
            return str(candidato)
        for candidato in base.rglob("exiftool(-k).exe"):
            return str(candidato)

    # Búsqueda en PATH
    p = shutil.which("exiftool")
    if p:
        return p
    return None


def exiftool_version(exiftool_path):
    """Devuelve la versión de ExifTool o None si falla."""
    try:
        proc = subprocess.run(
            [exiftool_path, "-ver"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        return proc.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lectura de fechas en lote
# ---------------------------------------------------------------------------
def read_dates_batch(files, exiftool_path, chunk_size=200, progress=None):
    """Lee las fechas de una lista de archivos usando ExifTool en lotes.

    chunk_size bajo (200) para no superar el límite de línea de comandos
    de Windows (~32.767 caracteres). Devuelve:
    dict {ruta_normalizada: {tag: valor}}
    """
    resultados = {}
    total = len(files)
    for i in range(0, total, chunk_size):
        lote = files[i:i + chunk_size]
        cmd = [exiftool_path, "-j", "-G", "-n"] + TAGS_FECHA + lote
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600,
            )
            # exiftool puede devolver código != 0 si algún archivo falla,
            # pero aun así emite el JSON de los que sí pudo leer.
            if proc.stdout.strip():
                datos = json.loads(proc.stdout)
                for d in datos:
                    src = d.get("SourceFile")
                    if src:
                        resultados[os.path.normpath(src)] = {
                            k: v for k, v in d.items() if k != "SourceFile"
                        }
        except Exception:
            # Lote fallido: registrar vacío para no detener el proceso
            for f in lote:
                resultados[os.path.normpath(f)] = {}
        if progress:
            progress(min(i + len(lote), total), total)
    return resultados


def buscar_metadatos(resultados, ruta):
    """Busca los metadatos de una ruta.

    Primero intenta la coincidencia exacta de ruta. Si falla (ExifTool
    reemplaza caracteres no ASCII por '?' en la salida en Windows), busca
    por (nombre de archivo, tamaño), que es inmune a ese problema.

    Devuelve: dict de metadatos (vacío si no hay).
    """
    r = resultados.get(os.path.normpath(ruta))
    if r is not None:
        return r
    nombre = os.path.basename(ruta).lower()
    try:
        tam = os.path.getsize(ruta)
    except OSError:
        return {}
    for k, v in resultados.items():
        if (os.path.basename(k).lower() == nombre
                and v.get("File:FileSize") == tam):
            return v
    return {}


# ---------------------------------------------------------------------------
# Normalización y selección de fechas
# ---------------------------------------------------------------------------
def _normalizar_fecha(valor):
    """Convierte '2023:06:15 14:30:22' (o variantes) a 'YYYY-MM-DD HH:MM:SS'.

    Devuelve None si no es una fecha válida.
    """
    if not valor:
        return None
    s = str(valor).strip()
    # Con hora (puede traer zona horaria al final, p.ej. '+02:00' o 'Z')
    m = re.match(r"(\d{4})[:.-](\d{2})[:.-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi, se = m.groups()
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{mo}-{d} {h}:{mi}:{se}"
    # Solo fecha
    m = re.match(r"(\d{4})[:.-](\d{2})[:.-](\d{2})", s)
    if m:
        y, mo, d = m.groups()
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{mo}-{d} 00:00:00"
    return None


# Patrones de fecha en nombres de archivo (WhatsApp, cámaras, capturas...)
_PATRONES_NOMBRE = [
    # IMG_20230615_143022, VID_20230615_143022, PXL_..., Screenshot_20230615-143022
    re.compile(
        r"(?:IMG|VID|PXL|DSC|MVIMG|Screenshot|Screen_Shot|WhatsApp|Signal)"
        r"[-_ ]?(\d{4})(\d{2})(\d{2})[-_ ]?(\d{2})(\d{2})(\d{2})", re.I),
    # 20230615_143022
    re.compile(r"(\d{4})(\d{2})(\d{2})[-_ ](\d{2})(\d{2})(\d{2})(?!\d)"),
    # 2023-10-25 14.30.22 (WhatsApp), 2023-10-25_14-30-22
    re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})[ _-](\d{2})[.-](\d{2})[.-](\d{2})"),
    # 2023-10-25, 2023_10_25
    re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})(?!\d)"),
    # 20231025 (solo fecha)
    re.compile(r"(\d{4})(\d{2})(\d{2})(?!\d)"),
]

# Timestamps Unix en nombres (Nokia, Android, etc.): 13 dígitos = ms, 10 = s
_PATRON_UNIX_MS = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_PATRON_UNIX_S = re.compile(r"(?<!\d)(\d{10})(?!\d)")

# Rango de años plausibles para fechas de fotos
_ANIO_MIN, _ANIO_MAX = 1970, 2100


def parse_filename_date(nombre):
    """Extrae una fecha del nombre del archivo. Devuelve 'YYYY-MM-DD HH:MM:SS' o None."""
    # 1) Timestamps Unix (13 dígitos = milisegundos, 10 = segundos)
    m = _PATRON_UNIX_MS.search(nombre)
    if m:
        try:
            import datetime
            return datetime.datetime.fromtimestamp(
                int(m.group(1)) / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            pass
    m = _PATRON_UNIX_S.search(nombre)
    if m:
        try:
            import datetime
            return datetime.datetime.fromtimestamp(
                int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            pass

    # 2) Patrones de fecha explícitos
    for patron in _PATRONES_NOMBRE:
        m = patron.search(nombre)
        if not m:
            continue
        grupos = m.groups()
        y, mo, d = grupos[0], grupos[1], grupos[2]
        if not (_ANIO_MIN <= int(y) <= _ANIO_MAX
                and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
            continue
        if len(grupos) == 6:
            h, mi, se = grupos[3], grupos[4], grupos[5]
            if int(h) > 23 or int(mi) > 59 or int(se) > 59:
                continue
            return f"{y}-{mo}-{d} {h}:{mi}:{se}"
        return f"{y}-{mo}-{d} 00:00:00"
    return None


def pick_date(metadata, ruta):
    """Elige la mejor fecha según la cadena de prioridad.

    Devuelve: (fecha_normalizada, fuente) donde fuente puede ser:
      'EXIF:DateTimeOriginal', 'QuickTime:CreationDate', ..., 'nombre',
      'filesystem-dudosa', o (None, None) si no hay nada.
    """
    for tag in PRIORIDAD_METADATA:
        v = metadata.get(tag)
        if v:
            f = _normalizar_fecha(v)
            if f:
                return f, tag

    # Patrón en el nombre de archivo
    f = parse_filename_date(Path(ruta).name)
    if f:
        return f, "nombre"

    # Último recurso: fecha de modificación del archivo (marcada como dudosa)
    v = metadata.get("File:FileModifyDate")
    if v:
        f = _normalizar_fecha(v)
        if f:
            return f, "filesystem-dudosa"

    return None, None


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def hash_muestra(ruta, tam_muestra=16 * 1024):
    """Hash MD5 de muestra: inicio + medio + final (rápido, para candidatos)."""
    h = hashlib.md5()
    try:
        tam = os.path.getsize(ruta)
        with open(ruta, "rb") as f:
            for pos in (0, tam // 2, max(0, tam - tam_muestra)):
                f.seek(pos)
                h.update(f.read(tam_muestra))
    except OSError:
        return None
    return h.hexdigest()


def hash_completo(ruta, chunk=1024 * 1024):
    """Hash MD5 completo del archivo (lento pero definitivo)."""
    h = hashlib.md5()
    try:
        with open(ruta, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()