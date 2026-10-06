# -*- coding: utf-8 -*-
r"""
organizar.py — FASE 2: Ordenamiento por fecha de captura.

Copia (por defecto) cada archivo multimedia a:
    destino\YYYY\MM\archivo.ext        (fecha de captura real)
    destino\sin_fecha\archivo.ext      (sin fecha detectable)

El origen NUNCA se modifica en modo copiar. Con --modo mover se mueven
los archivos (libera espacio, pero requiere confirmación del usuario).

Cadena de prioridad de la fecha:
    1. EXIF:DateTimeOriginal        (fecha de disparo de la cámara)
    2. EXIF:DateTimeDigitized / EXIF:CreateDate
    3. QuickTime:CreationDate / CreateDate (videos MP4/MOV/M4V)
    4. Patrón de fecha en el nombre del archivo
    5. Fecha de archivo (filesystem) -> marcada como DUDOSA en el log
    6. Sin fecha -> carpeta sin_fecha\

Uso:
    python src\organizar.py --origen "D:\ruta\a\tus\fotos"
    python src\organizar.py --origen "D:\ruta\a\tus\fotos" --destino "E:\Fotos_Ordenadas"
    python src\organizar.py --origen "D:\ruta\a\tus\fotos" --modo mover

Salidas (en logs/ junto a la raíz del proyecto, por defecto):
    ordenacion.csv          : trazabilidad completa (origen -> destino -> fecha -> fuente)
    resumen_ordenacion.txt  : totales
    errores.txt             : archivos que fallaron
"""

import argparse
import csv
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def _dentro_de(p, base):
    """True si la ruta p está dentro de base (o es base)."""
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _copiar_con_colisiones(origen, carpeta, nombre, modo):
    """Copia/mueve manejando colisiones de nombre.

    Devuelve: (ruta_destino, estado)
      estado: 'copiado' | 'movido' | 'omitido-ya-existente'
    """
    candidato = carpeta / nombre
    if candidato.exists():
        # Mismo tamaño -> comparar hash completo (resume o duplicado real)
        if candidato.stat().st_size == os.path.getsize(origen):
            if (exif_utils.hash_completo(candidato) ==
                    exif_utils.hash_completo(origen)):
                return candidato, "omitido-ya-existente"
        # Colisión real: buscar nombre libre con sufijo _1, _2, ...
        base = candidato.stem
        ext = candidato.suffix
        i = 1
        while True:
            candidato = carpeta / f"{base}_{i}{ext}"
            if not candidato.exists():
                break
            i += 1

    if modo == "mover":
        shutil.move(origen, candidato)
        return candidato, "movido"
    shutil.copy2(origen, candidato)
    return candidato, "copiado"


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Ordena fotos y videos por fecha de captura (copia por defecto).")
    ap.add_argument("--origen", required=True,
                    help="Carpeta raíz con los archivos desordenados")
    ap.add_argument("--destino", default=None,
                    help="Carpeta destino (por defecto: destino/ en la raíz del proyecto)")
    ap.add_argument("--modo", choices=["copiar", "mover"], default="copiar",
                    help="copiar = origen intacto (por defecto); mover = libera espacio")
    ap.add_argument("--extensiones", default=None,
                    help="Solo estas extensiones, separadas por coma (p.ej. jpg,png,mp4). "
                         "Por defecto: todas las multimedia.")
    args = ap.parse_args()

    origen = Path(args.origen).resolve()
    if not origen.is_dir():
        sys.exit(f"ERROR: la carpeta origen no existe: {origen}")

    carpeta_proyecto = exif_utils.PROJECT_ROOT
    destino = Path(args.destino).resolve() if args.destino else \
        carpeta_proyecto / "destino"

    # Seguridad: el destino no puede estar dentro del origen (ni al revés)
    if _dentro_de(destino, origen):
        sys.exit("ERROR: la carpeta destino está DENTRO de la carpeta origen.\n"
                 "       Elige un destino fuera del origen (p.ej. otra carpeta o disco).")
    if _dentro_de(origen, destino):
        sys.exit("ERROR: la carpeta origen está DENTRO de la carpeta destino.")

    if args.modo == "mover":
        print("AVISO: modo MOVER. Los archivos se moverán (no se copiarán).")
        resp = input("¿Continuar? (s/N): ").strip().lower()
        if resp != "s":
            sys.exit("Cancelado por el usuario.")

    # Filtro de extensiones
    ext_filtro = None
    if args.extensiones:
        ext_filtro = {("." + e.strip().lower().lstrip("."))
                      for e in args.extensiones.split(",") if e.strip()}

    exiftool = exif_utils.find_exiftool()
    if not exiftool:
        sys.exit("ERROR: no se encontró exiftool.exe. Colócalo junto a los scripts o en PATH.")
    version = exif_utils.exiftool_version(exiftool)
    print(f"ExifTool detectado: {exiftool} (versión {version or 'desconocida'})")
    print(f"Origen : {origen}")
    print(f"Destino: {destino}")
    print(f"Modo   : {args.modo}")

    # ------------------------------------------------------------------
    # 1) Inventario (podando el destino y la carpeta del proyecto si están dentro)
    # ------------------------------------------------------------------
    archivos = []
    for root, dirs, files in os.walk(origen):
        dirs[:] = [d for d in dirs
                   if not _dentro_de(Path(root) / d, destino)
                   and not _dentro_de(Path(root) / d, carpeta_proyecto)]
        for nombre in files:
            p = Path(root) / nombre
            ext = p.suffix.lower()
            if ext not in exif_utils.EXT_MULTIMEDIA:
                continue
            if ext_filtro and ext not in ext_filtro:
                continue
            try:
                tam = p.stat().st_size
            except OSError:
                continue
            archivos.append((str(p), ext, tam))

    total = len(archivos)
    if total == 0:
        sys.exit("No se encontraron archivos multimedia para procesar.")
    print(f"Archivos a procesar: {total} "
          f"({sum(t for _, _, t in archivos) / 1e9:.2f} GB)")

    # ------------------------------------------------------------------
    # 2) Lectura de fechas en lote
    # ------------------------------------------------------------------
    print("Leyendo fechas con ExifTool...")
    rutas = [a[0] for a in archivos]
    metadatos = exif_utils.read_dates_batch(
        rutas, exiftool,
        progress=lambda done, tot: print(f"  {done}/{tot} archivos", end="\r"))
    print()

    # ------------------------------------------------------------------
    # 3) Copia/ordenamiento
    # ------------------------------------------------------------------
    logs_dir = carpeta_proyecto / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    destino.mkdir(parents=True, exist_ok=True)

    filas = []
    errores = []
    estados = Counter()

    for idx, (ruta, ext, tam) in enumerate(archivos, 1):
        fecha, fuente = exif_utils.pick_date(
            exif_utils.buscar_metadatos(metadatos, ruta), ruta)
        if fecha:
            carpeta = destino / fecha[:4] / fecha[5:7]
        else:
            carpeta = destino / "sin_fecha"
        nombre = Path(ruta).name
        dest_final = None
        estado = "error"
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            dest_final, estado = _copiar_con_colisiones(ruta, carpeta, nombre, args.modo)
        except Exception as e:
            errores.append([ruta, str(e)])
        filas.append([ruta, str(dest_final) if dest_final else "",
                      fecha or "", fuente or "", estado])
        estados[estado] += 1
        if idx % 100 == 0 or idx == total:
            print(f"  {idx}/{total}  último: {estado}", end="\r")
    print()

    # ------------------------------------------------------------------
    # 4) Escritura de logs
    # ------------------------------------------------------------------
    with open(logs_dir / "ordenacion.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ruta_origen", "ruta_destino", "fecha", "fuente", "estado"])
        w.writerows(filas)

    with open(logs_dir / "errores.txt", "w", encoding="utf-8", newline="\n") as f:
        if errores:
            f.write("\n".join(f"{r} :: {e}" for r, e in errores) + "\n")
        else:
            f.write("(sin errores)\n")

    lineas = ["RESUMEN DE ORDENACIÓN",
              "=" * 60,
              f"Modo                 : {args.modo}",
              f"Origen               : {origen}",
              f"Destino              : {destino}",
              "-" * 60]
    for estado in sorted(estados):
        lineas.append(f"{estado:<22}: {estados[estado]:>8}")
    lineas.append("-" * 60)
    lineas.append(f"{'TOTAL':<22}: {total:>8}")
    lineas.append("")
    lineas.append("Fuentes de fecha usadas:")
    fuentes = Counter(f[3] for f in filas if f[3])
    for fuente, n in sorted(fuentes.items(), key=lambda x: -x[1]):
        lineas.append(f"  {fuente:<28}: {n:>8}")
    _escribir_utf8(logs_dir / "resumen_ordenacion.txt", lineas)

    # ------------------------------------------------------------------
    # 5) Resumen en pantalla
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("ORDENACIÓN COMPLETADA")
    print("=" * 60)
    for estado in sorted(estados):
        print(f"{estado:<22}: {estados[estado]}")
    print(f"Errores: {len(errores)}")
    print()
    print(f"Estructura creada en: {destino}")
    print(f"Logs en: {logs_dir}")
    if estados.get("filesystem-dudosa") or any(f[4] == "copiado" and f[3] == "filesystem-dudosa" for f in filas):
        print("NOTA: hay archivos con fecha DUDOSA (filesystem). Revisa el CSV.")


if __name__ == "__main__":
    main()