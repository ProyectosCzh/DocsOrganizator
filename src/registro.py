# -*- coding: utf-8 -*-
r"""
registro.py — Libro mayor de archivos ya respaldados.

Genera un inventario completo con hash MD5 de cada archivo de una carpeta.
Ese CSV es el "registro de lo que ya tenes": sirve para

  1) saber qué fotos estan respaldadas (y therefore cuáles podes borrar),
  2) deduplicar futuras importaciones por contenido (ver importar.py).

NUNCA borra ni modifica los archivos de la carpeta analizada: solo lee.

Uso:
    python src\registro.py --carpeta "E:\Fotos_Ordenadas"
    python src\registro.py --carpeta "E:\Fotos_Ordenadas" --modo reconstruir
    python src\registro.py --carpeta "E:\Fotos_Ordenadas" --verificar

Modos:
    actualizar  (por defecto) agrega al registro los archivos de la carpeta
                que aun no esten en el CSV. NUNCA borra filas: el registro
                es historico (sirve aunque borres la carpeta despues).
    reconstruir borra el CSV y lo vuelve a generar desde la carpeta.

Salidas (en registro/ junto a la raíz del proyecto, por defecto):
    registro/respaldo.csv    : nombre, tamano, md5, fecha_mod, origen
    registro/errores.txt     : archivos que no se pudieron hashear
    registro/resumen.txt     : totales
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def _fecha_mod(path):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


def _cargar_origenes(log_unificacion):
    """mapa nombre_destino -> carpeta de origen (para trazabilidad)."""
    if not log_unificacion.exists():
        return {}
    mapa = {}
    with open(log_unificacion, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 5 and row[4] == "copiado" and row[1]:
                mapa[os.path.basename(row[1])] = os.path.dirname(row[0])
    return mapa


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Genera el registro (hash) de archivos ya respaldados.")
    ap.add_argument("--carpeta", required=True,
                    help="Carpeta a inventariar (solo lectura)")
    ap.add_argument("--salida", default=None,
                    help="Archivo CSV de salida (por defecto: registro/respaldo.csv "
                         "en la raíz del proyecto)")
    ap.add_argument("--modo", choices=["actualizar", "reconstruir"], default="actualizar",
                    help="actualizar = agrega faltantes, conserva el historico; "
                         "reconstruir = rehace el CSV desde cero")
    ap.add_argument("--verificar", action="store_true",
                    help="Solo verificar el CSV existente contra la carpeta")
    args = ap.parse_args()

    carpeta = Path(args.carpeta)
    if not carpeta.is_dir():
        sys.exit(f"ERROR: la carpeta no existe: {carpeta}")

    proyecto = exif_utils.PROJECT_ROOT
    salida = Path(args.salida) if args.salida else proyecto / "registro" / "respaldo.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)
    log_unif = proyecto / "logs" / "unificacion.csv"
    origenes = _cargar_origenes(log_unif)

    # ------------------------------------------------------------------
    # 0) Modo verificar: comprueba el CSV contra la carpeta
    # ------------------------------------------------------------------
    if args.verificar:
        if not salida.exists():
            sys.exit(f"ERROR: no existe el registro: {salida}")
        with open(salida, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        faltan_hash = [r for r in rows if not r.get("md5", "").strip()]
        en_carpeta = {e.name for e in os.scandir(carpeta) if e.is_file()}
        registrados = {r["nombre"] for r in rows}
        no_registrados = sorted(en_carpeta - registrados)
        borrados = sorted(registrados - en_carpeta)
        print(f"Filas en el registro : {len(rows)}")
        print(f"Sin hash (error)      : {len(faltan_hash)}")
        print(f"En carpeta sin fila   : {len(no_registrados)}")
        for n in no_registrados[:20]:
            print("   +", n)
        print(f"En registro sin archivo (historico, ok si borraste): {len(borrados)}")
        return

    # ------------------------------------------------------------------
    # Cargar registro existente (modo actualizar)
    # ------------------------------------------------------------------
    existentes = set()   # (nombre, tamano)
    claves = set()       # (tamano, md5)
    if args.modo == "actualizar" and salida.exists():
        with open(salida, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    clave = (r["nombre"], int(r["tamano_bytes"]))
                except (KeyError, ValueError):
                    continue
                existentes.add(clave)
                if r.get("md5", "").strip():
                    claves.add((clave[1], r["md5"].strip()))
        print(f"Registro existente: {len(existentes)} filas | "
              f"{len(claves)} hashes de contenido")
    elif args.modo == "reconstruir":
        print("Modo RECONSTRUIR: se reemplazara el CSV actual.")

    # ------------------------------------------------------------------
    # Inventario de la carpeta
    # ------------------------------------------------------------------
    archivos = [e.path for e in os.scandir(carpeta) if e.is_file()]
    pendientes = []
    for p in archivos:
        try:
            tam = os.path.getsize(p)
        except OSError:
            continue
        if (os.path.basename(p), tam) not in existentes:
            pendientes.append((p, tam))
    total_carpeta = len(archivos)
    total_bytes = sum(os.path.getsize(p) for p in archivos)
    print(f"Archivos en la carpeta: {total_carpeta} ({total_bytes / 1e9:.2f} GB)")
    print(f"Pendientes de hashear : {len(pendientes)}")

    # ------------------------------------------------------------------
    # Hashear y escribir (incremental, reanudable)
    # ------------------------------------------------------------------
    nuevo = not (args.modo == "actualizar" and salida.exists())
    csv_file = open(salida, "a" if not nuevo else "w", encoding="utf-8", newline="")
    writer = csv.writer(csv_file)
    if nuevo:
        writer.writerow(["nombre", "tamano_bytes", "md5",
                         "fecha_modificacion", "origen"])
        csv_file.flush()

    errores = []
    agregados = 0
    t0 = time.time()
    for i, (p, tam) in enumerate(pendientes, 1):
        h = exif_utils.hash_completo(p)
        nombre = os.path.basename(p)
        if h:
            writer.writerow([nombre, tam, h, _fecha_mod(p),
                             origenes.get(nombre, "")])
            claves.add((tam, h))
            agregados += 1
        else:
            errores.append([nombre, "no se pudo calcular MD5"])
        if i % 200 == 0 or i == len(pendientes):
            csv_file.flush()
            print(f"  {i}/{len(pendientes)} | agregados={agregados} "
                  f"| errores={len(errores)} | {time.time() - t0:.0f}s", flush=True)
    csv_file.close()

    with open(salida.parent / "errores.txt", "w", encoding="utf-8", newline="\n") as f:
        if errores:
            f.write("\n".join(f"{n} :: {e}" for n, e in errores) + "\n")
        else:
            f.write("(sin errores)\n")

    # total de filas ahora
    with open(salida, encoding="utf-8") as f:
        total_filas = sum(1 for _ in f) - 1

    lineas = ["RESUMEN DEL REGISTRO",
              "=" * 60,
              f"Modo       : {args.modo}",
              f"Carpeta    : {carpeta}",
              f"Registro   : {salida}",
              "-" * 60,
              f"Archivos en la carpeta   : {total_carpeta}",
              f"Filas en el registro     : {total_filas}",
              f"Agregados en esta corrida: {agregados}",
              f"Contenidos unicos (hash) : {len(claves)}",
              f"Errores                  : {len(errores)}"]
    _escribir_utf8(salida.parent / "resumen.txt", lineas)

    print()
    print("=" * 60)
    print("REGISTRO ACTUALIZADO")
    print("=" * 60)
    print(f"Agregados ahora   : {agregados}")
    print(f"Filas totales     : {total_filas}")
    print(f"Contenidos unicos : {len(claves)}")
    print(f"Errores           : {len(errores)}")
    print(f"Archivo: {salida}")


if __name__ == "__main__":
    main()
