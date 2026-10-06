# -*- coding: utf-8 -*-
r"""
dedup.py — FASE 3 (opcional): Deduplicación por hash completo.

Escanea una carpeta (típicamente el destino ordenado), agrupa archivos con el
mismo tamaño y el MISMO hash MD5 completo, y reporta los duplicados.
NUNCA elimina nada: con --mover, las copias redundantes se MUEVEN a
carpeta\duplicados\ (preservando la estructura relativa).

Uso:
    python src\dedup.py --carpeta "E:\Fotos_Ordenadas\destino"
    python src\dedup.py --carpeta "E:\Fotos_Ordenadas\destino" --mover

Salidas (en logs/ junto a la raíz del proyecto, por defecto):
    duplicados_confirmados.csv  : grupos de duplicados confirmados por hash
    resumen_duplicados.txt      : totales
"""

import argparse
import csv
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Detecta duplicados por hash completo. No borra nada: "
                    "con --mover, mueve copias a duplicados/.")
    ap.add_argument("--carpeta", required=True,
                    help="Carpeta a analizar (p.ej. el destino ordenado)")
    ap.add_argument("--mover", action="store_true",
                    help="Mover copias redundantes a duplicados/ (por defecto solo reporta)")
    ap.add_argument("--salida", default=None,
                    help="Carpeta de salidas (por defecto: logs/ en la raíz del proyecto)")
    args = ap.parse_args()

    carpeta = Path(args.carpeta).resolve()
    if not carpeta.is_dir():
        sys.exit(f"ERROR: la carpeta no existe: {carpeta}")

    salida = Path(args.salida) if args.salida else \
        exif_utils.PROJECT_ROOT / "logs"
    salida.mkdir(parents=True, exist_ok=True)

    carpeta_dup = carpeta / "duplicados"

    # ------------------------------------------------------------------
    # 1) Inventario (ignora la propia carpeta duplicados)
    # ------------------------------------------------------------------
    archivos = []
    for root, dirs, files in os.walk(carpeta):
        dirs[:] = [d for d in dirs if (Path(root) / d) != carpeta_dup]
        for nombre in files:
            p = Path(root) / nombre
            try:
                tam = p.stat().st_size
            except OSError:
                continue
            archivos.append((str(p), tam))

    total = len(archivos)
    print(f"Archivos en '{carpeta}': {total}")
    if total == 0:
        sys.exit("No hay archivos para analizar.")

    # ------------------------------------------------------------------
    # 2) Hash completo (MD5) y agrupación
    # ------------------------------------------------------------------
    print("Calculando hash completo de cada archivo (puede tardar)...")
    grupos = defaultdict(list)
    for i, (ruta, tam) in enumerate(archivos, 1):
        h = exif_utils.hash_completo(ruta)
        if h:
            grupos[(tam, h)].append(ruta)
        if i % 200 == 0 or i == total:
            print(f"  {i}/{total}", end="\r")
    print()

    dups = {k: v for k, v in grupos.items() if len(v) > 1}
    total_en_dups = sum(len(v) for v in dups.values())
    redundantes = sum(len(v) - 1 for v in dups.values())

    # ------------------------------------------------------------------
    # 3) Reporte CSV
    # ------------------------------------------------------------------
    with open(salida / "duplicados_confirmados.csv", "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "tamano_bytes", "hash_md5", "estado", "ruta"])
        for i, ((tam, h), lista) in enumerate(sorted(dups.items()), 1):
            lista_ordenada = sorted(lista, key=len)
            for j, ruta in enumerate(lista_ordenada):
                estado = "conservar" if j == 0 else "redundante"
                w.writerow([i, tam, h, estado, ruta])

    # ------------------------------------------------------------------
    # 4) Mover redundantes (opcional)
    # ------------------------------------------------------------------
    movidos = 0
    if args.mover and dups:
        print("Moviendo copias redundantes a duplicados/ ...")
        for (tam, h), lista in dups.items():
            lista_ordenada = sorted(lista, key=len)
            for extra in lista_ordenada[1:]:
                p = Path(extra)
                if carpeta_dup in p.parents:
                    continue  # ya está en duplicados
                try:
                    rel = p.relative_to(carpeta)
                except ValueError:
                    continue
                dest = carpeta_dup / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    # No sobrescribir: añadir sufijo
                    i = 1
                    while True:
                        cand = dest.with_name(f"{dest.stem}_{i}{dest.suffix}")
                        if not cand.exists():
                            dest = cand
                            break
                        i += 1
                shutil.move(str(p), str(dest))
                movidos += 1
                print(f"  movido: {p}")

    # ------------------------------------------------------------------
    # 5) Resumen
    # ------------------------------------------------------------------
    lineas = ["RESUMEN DE DUPLICACIÓN",
              "=" * 60,
              f"Carpeta analizada     : {carpeta}",
              f"Archivos totales      : {total}",
              f"Grupos duplicados     : {len(dups)}",
              f"Archivos duplicados   : {total_en_dups}",
              f"Copias redundantes    : {redundantes}",
              f"Espacio redundante    : "
              f"{sum((tam * (len(v) - 1)) for (tam, h), v in dups.items()) / 1e6:.1f} MB",
              "-" * 60,
              f"Movidos a duplicados/ : {movidos if args.mover else 'no (modo reporte)'}"]
    _escribir_utf8(salida / "resumen_duplicados.txt", lineas)

    print()
    print("=" * 60)
    print("DEDUPLICACIÓN COMPLETADA")
    print("=" * 60)
    print(f"Grupos duplicados   : {len(dups)}")
    print(f"Archivos duplicados : {total_en_dups}")
    print(f"Redundantes         : {redundantes}")
    if args.mover:
        print(f"Movidos a duplicados/: {movidos}")
    else:
        print("Modo reporte (nada fue movido). Usa --mover para moverlos.")
    print(f"Reporte: {salida / 'duplicados_confirmados.csv'}")


if __name__ == "__main__":
    main()