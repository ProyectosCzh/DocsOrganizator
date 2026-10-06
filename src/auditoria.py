# -*- coding: utf-8 -*-
r"""
auditoria.py — FASE 1: Auditoría de solo lectura.

Escanea la carpeta origen y genera reportes SIN modificar, mover ni eliminar
ningún archivo. Sirve para conocer qué hay antes de ordenar.

Uso:
    python src\auditoria.py --origen "D:\ruta\a\tus\fotos"
    python src\auditoria.py --origen "D:\ruta\a\tus\fotos" --salida "D:\otra\carpeta\reportes"

Salidas (en reportes/ junto a la raíz del proyecto, por defecto):
    reporte_extensiones.txt      : inventario por extensión (nº archivos, tamaño)
    reporte_fechas.txt           : resumen de disponibilidad de fechas + histograma por año
    metadatos.csv                : por archivo: ruta, fecha hallada, fuente
    duplicados_candidatos.csv    : posibles duplicados (tamaño + hash de muestra)
    muestra_sin_fecha.txt        : ejemplos de archivos sin fecha detectable
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    """Escribe líneas de texto en UTF-8 (compatible con Windows)."""
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Auditoría de solo lectura de la biblioteca multimedia.")
    ap.add_argument("--origen", required=True,
                    help="Carpeta raíz a analizar (solo lectura)")
    ap.add_argument("--salida", default=None,
                    help="Carpeta de reportes (por defecto: reportes/ en la raíz del proyecto)")
    args = ap.parse_args()

    origen = Path(args.origen)
    if not origen.is_dir():
        sys.exit(f"ERROR: la carpeta origen no existe: {origen}")

    salida = Path(args.salida) if args.salida else \
        exif_utils.PROJECT_ROOT / "reportes"
    salida.mkdir(parents=True, exist_ok=True)

    exiftool = exif_utils.find_exiftool()
    if not exiftool:
        sys.exit("ERROR: no se encontró exiftool.exe. Colócalo junto a los scripts o en PATH.")
    version = exif_utils.exiftool_version(exiftool)
    print(f"ExifTool detectado: {exiftool} (versión {version or 'desconocida'})")
    print(f"Origen : {origen}")
    print(f"Salida : {salida}")
    print("Recorriendo carpetas (solo lectura)...")

    # ------------------------------------------------------------------
    # 1) Inventario de archivos multimedia
    # ------------------------------------------------------------------
    archivos = []  # (ruta, extension, tamaño)
    for root, dirs, files in os.walk(origen):
        for nombre in files:
            p = Path(root) / nombre
            ext = p.suffix.lower()
            if ext in exif_utils.EXT_MULTIMEDIA:
                try:
                    tam = p.stat().st_size
                except OSError:
                    continue
                archivos.append((str(p), ext, tam))

    total_archivos = len(archivos)
    total_bytes = sum(t for _, _, t in archivos)
    print(f"Archivos multimedia encontrados: {total_archivos} "
          f"({total_bytes / 1e9:.2f} GB)")

    if total_archivos == 0:
        sys.exit("No se encontraron archivos multimedia en la carpeta origen.")

    # ------------------------------------------------------------------
    # 2) Lectura de fechas en lote con ExifTool
    # ------------------------------------------------------------------
    print("Leyendo metadatos con ExifTool (puede tardar varios minutos)...")
    rutas = [a[0] for a in archivos]
    metadatos = exif_utils.read_dates_batch(
        rutas, exiftool,
        progress=lambda done, tot: print(f"  {done}/{tot} archivos", end="\r"))
    print()

    # ------------------------------------------------------------------
    # 3) Clasificación por disponibilidad de fecha
    # ------------------------------------------------------------------
    con_fecha = []      # fecha real de captura (EXIF/QuickTime/RIFF)
    por_nombre = []     # fecha extraída del nombre del archivo
    dudosos = []        # solo fecha de archivo (filesystem)
    sin_fecha = []      # sin ninguna fecha
    por_anio = Counter()
    filas_csv = []

    for ruta, ext, tam in archivos:
        fecha, fuente = exif_utils.pick_date(
            exif_utils.buscar_metadatos(metadatos, ruta), ruta)
        filas_csv.append([ruta, ext, tam, fecha or "", fuente or ""])
        if not fecha:
            sin_fecha.append(ruta)
            continue
        por_anio[fecha[:4]] += 1
        if fuente.startswith(("EXIF", "QuickTime", "RIFF")):
            con_fecha.append(ruta)
        elif fuente == "nombre":
            por_nombre.append(ruta)
        else:
            dudosos.append(ruta)

    # ------------------------------------------------------------------
    # 4) Detección preliminar de duplicados (tamaño + hash de muestra)
    # ------------------------------------------------------------------
    print("Buscando posibles duplicados (hash de muestra)...")
    grupos_dup = defaultdict(list)
    for ruta, ext, tam in archivos:
        h = exif_utils.hash_muestra(ruta)
        if h:
            grupos_dup[(tam, h)].append(ruta)
    candidatos = {k: v for k, v in grupos_dup.items() if len(v) > 1}

    # ------------------------------------------------------------------
    # 5) Escritura de reportes
    # ------------------------------------------------------------------
    # 5.1 Inventario por extensión
    por_ext = defaultdict(lambda: [0, 0])
    for _, ext, tam in archivos:
        por_ext[ext][0] += 1
        por_ext[ext][1] += tam

    lineas = ["INVENTARIO POR EXTENSIÓN",
              "=" * 60,
              f"{'Extensión':<10} {'Archivos':>10} {'Tamaño (MB)':>14} {'% del total':>12}",
              "-" * 60]
    for ext in sorted(por_ext, key=lambda e: -por_ext[e][1]):
        n, t = por_ext[ext]
        lineas.append(f"{ext:<10} {n:>10} {t / 1e6:>14.1f} "
                      f"{100.0 * t / total_bytes:>11.1f}%")
    lineas.append("-" * 60)
    lineas.append(f"{'TOTAL':<10} {total_archivos:>10} {total_bytes / 1e6:>14.1f} "
                  f"{'100.0%':>12}")
    _escribir_utf8(salida / "reporte_extensiones.txt", lineas)

    # 5.2 Resumen de fechas + histograma por año
    lineas = ["RESUMEN DE FECHAS",
              "=" * 60,
              f"Total de archivos multimedia : {total_archivos}",
              f"Con fecha de captura (EXIF/QuickTime/RIFF): {len(con_fecha)} "
              f"({100.0 * len(con_fecha) / total_archivos:.1f}%)",
              f"Con fecha solo en el nombre     : {len(por_nombre)} "
              f"({100.0 * len(por_nombre) / total_archivos:.1f}%)",
              f"Solo fecha de archivo (DUDOSA)  : {len(dudosos)} "
              f"({100.0 * len(dudosos) / total_archivos:.1f}%)",
              f"Sin ninguna fecha (-> sin_fecha): {len(sin_fecha)} "
              f"({100.0 * len(sin_fecha) / total_archivos:.1f}%)",
              "",
              "DISTRIBUCIÓN POR AÑO (según la mejor fecha hallada)",
              "-" * 60,
              f"{'Año':<8} {'Archivos':>10}",
              "-" * 60]
    for anio in sorted(por_anio):
        lineas.append(f"{anio:<8} {por_anio[anio]:>10}")
    lineas.append("-" * 60)
    lineas.append(f"{'TOTAL':<8} {sum(por_anio.values()):>10}")
    _escribir_utf8(salida / "reporte_fechas.txt", lineas)

    # 5.3 CSV de metadatos por archivo
    with open(salida / "metadatos.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ruta", "extension", "tamano_bytes", "fecha", "fuente"])
        w.writerows(filas_csv)

    # 5.4 Duplicados candidatos
    with open(salida / "duplicados_candidatos.csv", "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "tamano_bytes", "hash_muestra", "archivos"])
        for i, ((tam, h), lista) in enumerate(sorted(candidatos.items()), 1):
            w.writerow([i, tam, h, ";".join(lista)])

    # 5.5 Muestra de archivos sin fecha
    lineas = ["MUESTRA DE ARCHIVOS SIN FECHA DETECTABLE (máx. 20)",
              "=" * 60]
    for ruta in sin_fecha[:20]:
        lineas.append(ruta)
    if not sin_fecha:
        lineas.append("(no hay archivos sin fecha)")
    _escribir_utf8(salida / "muestra_sin_fecha.txt", lineas)

    # ------------------------------------------------------------------
    # 6) Resumen en pantalla
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("AUDITORÍA COMPLETADA")
    print("=" * 60)
    print(f"Archivos multimedia        : {total_archivos}")
    print(f"Con fecha de captura       : {len(con_fecha)}")
    print(f"Con fecha en el nombre     : {len(por_nombre)}")
    print(f"Solo fecha de archivo (dudosa): {len(dudosos)}")
    print(f"Sin fecha                  : {len(sin_fecha)}")
    print(f"Posibles duplicados (grupos): {len(candidatos)}")
    print(f"Archivos duplicados (aprox.): "
          f"{sum(len(v) - 1 for v in candidatos.values())}")
    print()
    print(f"Reportes generados en: {salida}")
    print("  - reporte_extensiones.txt")
    print("  - reporte_fechas.txt")
    print("  - metadatos.csv")
    print("  - duplicados_candidatos.csv")
    print("  - muestra_sin_fecha.txt")


if __name__ == "__main__":
    main()