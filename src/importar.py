# -*- coding: utf-8 -*-
r"""
importar.py — Importa carpetas nuevas copiando SOLO lo que no esta respaldado.

Compara cada archivo de la carpeta origen contra el registro (registro/respaldo.csv)
por (tamaño + MD5):

  - Si el contenido YA está en el registro  -> NO se copia (queda registrado
    como 'ya-respaldo'). Aunque tenga otro nombre, se detecta.
  - Si el contenido es NUEVO                 -> se copia a destino\, se
    verifica (tamaño + hash) y se agrega al registro para futuras importaciones.

NUNCA borra nada: ni de la origen, ni del destino, ni del registro
(solo agrega filas al CSV).

Es reanudable: si se interrumpe, al re-ejecutar omite lo ya copiado
(usa logs/importacion.csv + el propio registro).

Uso tipico (varias carpetas nuevas):
    python src\importar.py --origen "D:\Fotos Nuevas 1" --carpeta-destino "E:\Fotos_Ordenadas"
    python src\importar.py --origen "D:\Fotos Nuevas 1" --origen "E:\otra" --carpeta-destino "E:\Fotos_Ordenadas"
    python src\importar.py --origen "D:\varias" --carpeta-destino "E:\Fotos_Ordenadas" --simular

Salidas (en logs/ junto a la raíz del proyecto, por defecto):
    logs/importacion.csv   : origen -> destino / estado, por archivo
    logs/resumen_importacion.txt
    logs/errores_importacion.txt
"""

import argparse
import csv
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def _cargar_registro(ruta):
    """Devuelve (set de (tamano, md5), dict nombre -> (tamano, md5))."""
    if not ruta.exists():
        return set(), {}
    claves = set()
    por_nombre = {}
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            md5 = (r.get("md5") or "").strip()
            if not md5:
                continue
            try:
                tam = int(r["tamano_bytes"])
            except (KeyError, ValueError):
                continue
            claves.add((tam, md5))
            por_nombre[r["nombre"]] = (tam, md5)
    return claves, por_nombre


def _cargar_procesados(ruta):
    """Rutas de origen ya tratadas en corridas previas."""
    if not ruta.exists():
        return set()
    hechos = set()
    with open(ruta, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 5 and row[0] and row[4] not in ("error",):
                hechos.add(row[0])
    return hechos


def _nombre_libre(carpeta, nombre):
    """Primer nombre libre sin sobrescribir (sufijo _1, _2...)."""
    if not (carpeta / nombre).exists():
        return nombre
    base = Path(nombre).stem
    ext = Path(nombre).suffix
    i = 1
    while (carpeta / f"{base}_{i}{ext}").exists():
        i += 1
    return f"{base}_{i}{ext}"


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Copia solo los archivos cuyo contenido no está en el registro.")
    ap.add_argument("--origen", action="append", required=True,
                    help="Carpeta(es) nueva(s) a importar (repetible)")
    ap.add_argument("--carpeta-destino", required=True,
                    help="Carpeta destino donde se copian los archivos nuevos (obligatoria)")
    ap.add_argument("--registro", default=None,
                    help="CSV del registro (por defecto: registro/respaldo.csv "
                         "en la raíz del proyecto)")
    ap.add_argument("--simular", action="store_true",
                    help="Solo informar qué se copiaría; no copia nada")
    ap.add_argument("--extensiones", default=None,
                    help="Filtro de extensiones, ej: jpg,mp4 (por defecto: todas)")
    args = ap.parse_args()

    proyecto = exif_utils.PROJECT_ROOT
    destino = Path(args.carpeta_destino)
    registro = Path(args.registro) if args.registro else proyecto / "registro" / "respaldo.csv"

    origenes = [Path(o).resolve() for o in args.origen]
    for o in origenes:
        if not o.is_dir():
            sys.exit(f"ERROR: la carpeta origen no existe: {o}")

    ext_filtro = None
    if args.extensiones:
        ext_filtro = {("." + e.strip().lower().lstrip("."))
                      for e in args.extensiones.split(",") if e.strip()}

    claves, por_nombre = _cargar_registro(registro)
    print(f"Registro cargado: {len(claves)} contenidos unicos ya respaldados")
    if not claves:
        print("AVISO: el registro esta vacio; se copiarian TODOS los archivos. "
              "Corre registro.py antes de importar.\n")

    # inventario de todas las carpetas origen
    archivos = []
    for base in origenes:
        for root, dirs, files in os.walk(base):
            for fn in files:
                p = Path(root) / fn
                if ext_filtro and p.suffix.lower() not in ext_filtro:
                    continue
                try:
                    tam = p.stat().st_size
                except OSError:
                    continue
                archivos.append((str(p), tam))
    if not archivos:
        sys.exit("No se encontraron archivos para importar.")
    total_bytes = sum(t for _, t in archivos)
    print(f"Archivos a evaluar: {len(archivos)} ({total_bytes / 1e9:.2f} GB)")

    # ------------------------------------------------------------------
    # Clasificar: ya respaldado vs nuevo
    # ------------------------------------------------------------------
    nuevos = []      # (ruta, tam, md5) para los que hay que copiar
    ya_respaldo = 0
    bytes_ya = 0
    for ruta, tam in archivos:
        h = exif_utils.hash_completo(ruta)
        if h is None:
            continue
        if (tam, h) in claves:
            ya_respaldo += 1
            bytes_ya += tam
        else:
            nuevos.append((ruta, tam, h))

    print()
    print(f"YA RESPALDADO (no se copia): {ya_respaldo} "
          f"({bytes_ya / 1e9:.2f} GB)")
    print(f"NUEVOS (a copiar)          : {len(nuevos)} "
          f"({sum(t for _, t, *_ in nuevos) / 1e9:.2f} GB)")

    if args.simular:
        print("\n--- SIMULACION: primeros 20 nuevos ---")
        for n in nuevos[:20]:
            print("   +", n[0])
        return

    # ------------------------------------------------------------------
    # Copiar los nuevos, verificando, y ampliar el registro
    # ------------------------------------------------------------------
    destino.mkdir(parents=True, exist_ok=True)
    logs_dir = proyecto / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_import = logs_dir / "importacion.csv"
    procesados = _cargar_procesados(log_import)

    nuevo_log = not log_import.exists()
    csv_file = open(log_import, "a" if not nuevo_log else "w", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if nuevo_log:
        csv_writer.writerow(["ruta_origen", "ruta_destino", "hash_md5",
                             "tamano_bytes", "estado"])
        csv_file.flush()

    reg_file = open(registro, "a", encoding="utf-8", newline="")
    reg_writer = csv.writer(reg_file)
    nuevo_reg = not registro.exists()
    if nuevo_reg:
        reg_writer.writerow(["nombre", "tamano_bytes", "md5",
                             "fecha_modificacion", "origen"])
        reg_file.flush()

    estados = Counter()
    errores = []
    t0 = time.time()
    n = len(nuevos)
    for i, item in enumerate(nuevos, 1):
        ruta, tam = item[0], item[1]
        h = item[2] if len(item) > 2 else None
        if ruta in procesados:
            estados["ya-procesado"] += 1
            continue
        nombre = Path(ruta).name
        final = _nombre_libre(destino, nombre)
        dest_path = destino / final
        try:
            shutil.copy2(ruta, str(dest_path))
            if os.path.getsize(str(dest_path)) != tam or \
                    exif_utils.hash_completo(str(dest_path)) != h:
                dest_path.unlink(missing_ok=True)
                raise IOError("verificacion post-copia fallo")
            estados["copiado"] += 1
            csv_writer.writerow([ruta, str(dest_path), h, tam, "copiado"])
            reg_writer.writerow([final, tam, h,
                                 time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(os.path.getmtime(str(dest_path)))),
                                 os.path.dirname(ruta)])
            claves.add((tam, h))
        except Exception as e:
            errores.append([ruta, str(e)])
            estados["error"] += 1
            csv_writer.writerow([ruta, "", h or "", tam, "error"])
        if i % 100 == 0 or i == n:
            csv_file.flush()
            reg_file.flush()
            print(f"  {i}/{n} | copiados={estados['copiado']} "
                  f"| ya-respaldo={ya_respaldo} | errores={len(errores)} "
                  f"| {time.time() - t0:.0f}s", flush=True)
    csv_file.close()
    reg_file.close()

    with open(logs_dir / "errores_importacion.txt", "w", encoding="utf-8", newline="\n") as f:
        if errores:
            f.write("\n".join(f"{r} :: {e}" for r, e in errores) + "\n")
        else:
            f.write("(sin errores)\n")

    lineas = ["RESUMEN DE IMPORTACION",
              "=" * 60,
              f"Origen(es)   : {', '.join(str(o) for o in origenes)}",
              f"Destino      : {destino}",
              f"Registro     : {registro}",
              "-" * 60,
              f"Archivos evaluados  : {len(archivos)}",
              f"Ya respaldado (NO copiado): {ya_respaldo}",
              f"Copiados (nuevos)  : {estados['copiado']}",
              f"Ya procesados      : {estados['ya-procesado']}",
              f"Errores            : {estados['error']}"]
    _escribir_utf8(logs_dir / "resumen_importacion.txt", lineas)

    print()
    print("=" * 60)
    print("IMPORTACION COMPLETADA")
    print("=" * 60)
    print(f"Ya respaldado (omitido): {ya_respaldo}")
    print(f"Copiados nuevos        : {estados['copiado']}")
    print(f"Errores                : {estados['error']}")
    print(f"Registro actualizado   : {registro} "
          f"({len(claves)} contenidos unicos)")


if __name__ == "__main__":
    main()