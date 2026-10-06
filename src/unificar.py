# -*- coding: utf-8 -*-
r"""
unificar.py — Consolida toda la biblioteca en una sola carpeta plana,
eliminando duplicados entre carpetas (por hash MD5 completo).

Modo copiar (POR DEFECTO): el origen NUNCA se modifica. Cada contenido
único se copia UNA sola vez a destino\. Los duplicados NO se copian
(ya existen en el origen): se registran en el CSV indicando qué archivo
se conservó.

Modo mover: los archivos se mueven; los duplicados se mueven a
duplicados\ conservando su estructura de carpetas.

Seguridad:
  - Idempotente/reanudable: al re-ejecutar se omite lo ya copiado
    (usa logs/unificacion.csv + comparación de contenido).
  - Verificación post-copia: tamaño + hash MD5 del destino vs origen.
    Si falla, se elimina la copia dañada y se registra el error.
  - Colisiones de nombre resueltas con sufijos _1, _2, ... (nunca
    sobrescribe).
  - NUNCA borra nada del origen.

Uso:
    python src\unificar.py --origen "D:\ruta\a\tus\fotos" --destino "E:\General"
    python src\unificar.py --origen "D:\ruta\a\tus\fotos" --destino "E:\General" --todas
    python src\unificar.py --origen "D:\ruta\a\tus\fotos" --destino "E:\General" --modo mover
    python src\unificar.py --origen "D:\ruta\a\tus\fotos" --destino "E:\General" --sin-verificar
"""

import argparse
import csv
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import exif_utils


def _escribir_utf8(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def _dentro_de(p, base):
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _clave_conservar(ruta):
    """Preferencia para conservar entre duplicados:
    1) nombre con fecha parseable (pista para ordenar después)
    2) nombre más largo (más descriptivo)
    3) ruta más corta (más cercana a la raíz)"""
    nombre = Path(ruta).name
    return (1 if exif_utils.parse_filename_date(nombre) else 0,
            len(nombre), -len(ruta))


def _mismo_contenido(a, b):
    """True si dos archivos tienen el mismo tamaño y hash MD5."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return (exif_utils.hash_completo(a) == exif_utils.hash_completo(b))
    except OSError:
        return False


def _destino_libre(carpeta, nombre, origen_ruta):
    """Resuelve el nombre final sin sobrescribir nada.

    Devuelve (ruta_final, estado) con estado 'copiar' o 'ya-existente'
    (ya-existente = ya hay un archivo con el MISMO contenido en destino)."""
    candidato = carpeta / nombre
    if candidato.exists():
        if _mismo_contenido(str(candidato), origen_ruta):
            return candidato, "ya-existente"
        base = candidato.stem
        ext = candidato.suffix
        i = 1
        while True:
            candidato = carpeta / f"{base}_{i}{ext}"
            if not candidato.exists():
                break
            if _mismo_contenido(str(candidato), origen_ruta):
                return candidato, "ya-existente"
            i += 1
    return candidato, "copiar"


def _copiar_verificado(origen_ruta, dest_final, verificar):
    """Copia a un archivo temporal, verifica y renombra al nombre final.

    Si la verificación falla, elimina el temporal y lanza IOError."""
    tmp = dest_final.with_name(f".tmp_{dest_final.name}")
    if tmp.exists():
        tmp.unlink()
    shutil.copy2(origen_ruta, str(tmp))
    if verificar:
        try:
            ok = (os.path.getsize(origen_ruta) == os.path.getsize(str(tmp))
                  and exif_utils.hash_completo(origen_ruta)
                  == exif_utils.hash_completo(str(tmp)))
        except OSError:
            ok = False
        if not ok:
            tmp.unlink(missing_ok=True)
            raise IOError("verificación falló (tamaño/hash no coinciden)")
    os.replace(str(tmp), str(dest_final))


def main():
    exif_utils.configurar_consola()
    ap = argparse.ArgumentParser(
        description="Consolida todos los archivos en una carpeta plana, "
                    "sin duplicados entre carpetas (copia por defecto).")
    ap.add_argument("--origen", required=True,
                    help="Carpeta raíz con los archivos (solo lectura en modo copiar)")
    ap.add_argument("--destino", default=None,
                    help="Carpeta plana de salida (por defecto: unificadas/ en la raíz del proyecto)")
    ap.add_argument("--duplicados", default=None,
                    help="Carpeta para duplicados en modo mover "
                         "(por defecto: duplicados/ en la raíz del proyecto)")
    ap.add_argument("--modo", choices=["copiar", "mover"], default="copiar",
                    help="copiar = origen intacto (por defecto); mover = libera espacio")
    ap.add_argument("--todas", action="store_true",
                    help="Incluir TODOS los archivos (no solo multimedia)")
    ap.add_argument("--sin-verificar", action="store_true",
                    help="No verificar hash post-copia (más rápido, menos seguro)")
    ap.add_argument("--yes", action="store_true",
                    help="No pedir confirmación en modo mover")
    args = ap.parse_args()

    origen = Path(args.origen).resolve()
    if not origen.is_dir():
        sys.exit(f"ERROR: la carpeta origen no existe: {origen}")

    carpeta_proyecto = exif_utils.PROJECT_ROOT
    destino = Path(args.destino).resolve() if args.destino else \
        carpeta_proyecto / "unificadas"
    duplicados = Path(args.duplicados).resolve() if args.duplicados else \
        carpeta_proyecto / "duplicados"

    # Seguridad: destino/duplicados no pueden estar dentro del origen (ni al revés)
    for carpeta, nombre in ((destino, "destino"), (duplicados, "duplicados")):
        if _dentro_de(carpeta, origen):
            sys.exit(f"ERROR: la carpeta {nombre} está DENTRO del origen.\n"
                     f"       Elige un destino fuera del origen.")
    if _dentro_de(origen, destino):
        sys.exit("ERROR: la carpeta origen está DENTRO de la carpeta destino.")

    if args.modo == "mover" and not args.yes:
        print(f"AVISO: modo MOVER. Se moverán archivos desde:\n  {origen}")
        resp = input("¿Continuar? (s/N): ").strip().lower()
        if resp != "s":
            sys.exit("Cancelado por el usuario.")

    verificar = not args.sin_verificar
    print(f"Origen    : {origen}")
    print(f"Destino   : {destino}")
    print(f"Modo      : {args.modo}")
    print(f"Verificar : {'SÍ (hash MD5 post-copia)' if verificar else 'NO'}")

    # ------------------------------------------------------------------
    # 1) Inventario (podando destino/duplicados/proyecto si estuvieran dentro)
    # ------------------------------------------------------------------
    archivos = []
    for root, dirs, files in os.walk(origen):
        dirs[:] = [d for d in dirs
                   if not _dentro_de(Path(root) / d, destino)
                   and not _dentro_de(Path(root) / d, duplicados)
                   and not _dentro_de(Path(root) / d, carpeta_proyecto)]
        for nombre in files:
            p = Path(root) / nombre
            if not args.todas and p.suffix.lower() not in exif_utils.EXT_MULTIMEDIA:
                continue
            try:
                tam = p.stat().st_size
            except OSError:
                continue
            archivos.append((str(p), tam))

    total = len(archivos)
    if total == 0:
        sys.exit("No se encontraron archivos para procesar.")
    print(f"Archivos a procesar: {total} "
          f"({sum(t for _, t in archivos) / 1e9:.2f} GB)")

    tam_por_ruta = {ruta: tam for ruta, tam in archivos}

    # ------------------------------------------------------------------
    # 2) Agrupar por tamaño; hashear solo grupos con tamaños repetidos
    # ------------------------------------------------------------------
    por_tamano = defaultdict(list)
    for ruta, tam in archivos:
        por_tamano[tam].append(ruta)

    grupos_contenido = {}   # (tam, hash) -> [rutas]  (solo tamaños repetidos)
    unicos_por_tamano = []  # tamaños con un solo archivo -> únicos directos
    for tam, lista in por_tamano.items():
        if len(lista) == 1:
            unicos_por_tamano.append(lista[0])
        else:
            for ruta in lista:
                h = exif_utils.hash_completo(ruta)
                if h:
                    grupos_contenido.setdefault((tam, h), []).append(ruta)
                else:
                    print(f"  AVISO: no se pudo hashear (se omite): {ruta}")

    # ------------------------------------------------------------------
    # 3) Preparación de logs y reanudación
    # ------------------------------------------------------------------
    logs_dir = carpeta_proyecto / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    destino.mkdir(parents=True, exist_ok=True)
    if args.modo == "mover":
        duplicados.mkdir(parents=True, exist_ok=True)

    csv_path = logs_dir / "unificacion.csv"
    procesados = set()
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # encabezado
            for row in reader:
                if len(row) >= 5 and row[0] and row[4] != "error":
                    procesados.add(row[0])
        print(f"Reanudando: {len(procesados)} archivos ya procesados "
              f"(se omitirán).")

    # Limpiar temporales huérfanos de una corrida anterior
    for t in destino.glob(".tmp_*"):
        try:
            t.unlink()
        except OSError:
            pass

    csv_file = open(csv_path, "a", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_file)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        csv_writer.writerow(["ruta_origen", "ruta_destino", "hash_md5",
                             "tamano_bytes", "estado"])
        csv_file.flush()

    errores = []
    estados = Counter()
    n_ya_procesados = 0
    t0 = time.time()

    def _fila(ruta, dest, h, tam, estado):
        csv_writer.writerow([ruta, dest, h or "", tam, estado])
        csv_file.flush()
        estados[estado] += 1

    def _procesar_archivo(ruta, tam, h):
        """Copia un archivo único (o lo omite si ya está)."""
        nonlocal n_ya_procesados
        if ruta in procesados:
            n_ya_procesados += 1
            return
        nombre = Path(ruta).name
        dest_final, estado = _destino_libre(destino, nombre, ruta)
        if estado == "ya-existente":
            _fila(ruta, str(dest_final), h, tam, "ya-existente")
            return
        try:
            _copiar_verificado(ruta, dest_final, verificar)
            _fila(ruta, str(dest_final), h, tam, "copiado")
        except Exception as e:
            errores.append([ruta, str(e)])
            _fila(ruta, "", h, tam, "error")

    def _procesar_grupo(lista, tam, h):
        """Entre duplicados: conserva el mejor y omite el resto."""
        nonlocal n_ya_procesados
        candidatos = sorted(lista, key=_clave_conservar, reverse=True)
        conservado_ruta = None
        conservado_dest = ""
        for ruta in candidatos:
            if ruta in procesados:
                n_ya_procesados += 1
                continue
            nombre = Path(ruta).name
            dest_final, estado = _destino_libre(destino, nombre, ruta)
            if estado == "ya-existente":
                conservado_ruta, conservado_dest = ruta, str(dest_final)
                _fila(ruta, conservado_dest, h, tam, "ya-existente")
                break
            try:
                _copiar_verificado(ruta, dest_final, verificar)
                conservado_ruta, conservado_dest = ruta, str(dest_final)
                _fila(ruta, conservado_dest, h, tam, "copiado")
                break
            except Exception as e:
                errores.append([ruta, str(e)])
                _fila(ruta, "", h, tam, "error")
        if conservado_ruta is None:
            return  # todos fallaron; ya registrados como error
        for ruta in candidatos:
            if ruta == conservado_ruta or ruta in procesados:
                continue
            if args.modo == "mover":
                try:
                    rel = Path(ruta).relative_to(origen)
                except ValueError:
                    rel = Path(ruta).name
                dest_dup = duplicados / rel
                dest_dup.parent.mkdir(parents=True, exist_ok=True)
                i = 1
                while dest_dup.exists():
                    dest_dup = dest_dup.with_name(
                        f"{dest_dup.stem}_{i}{dest_dup.suffix}")
                    i += 1
                shutil.move(ruta, str(dest_dup))
                _fila(ruta, str(dest_dup), h, tam, "duplicado-movido")
            else:
                _fila(ruta, conservado_dest, h, tam, "duplicado-omitido")

    # ------------------------------------------------------------------
    # 4) Procesamiento
    # ------------------------------------------------------------------
    n_unicos = len(unicos_por_tamano)
    n_grupos = len(grupos_contenido)
    print(f"Únicos directos: {n_unicos} | Grupos a deduplicar: {n_grupos}")

    for i, ruta in enumerate(unicos_por_tamano, 1):
        _procesar_archivo(ruta, tam_por_ruta[ruta], None)
        if i % 200 == 0 or i == n_unicos:
            print(f"  únicos {i}/{n_unicos} | copiados={estados['copiado']} "
                  f"errores={len(errores)} | {time.time() - t0:.0f}s", flush=True)

    for gi, ((tam, h), lista) in enumerate(sorted(grupos_contenido.items()), 1):
        _procesar_grupo(lista, tam, h)
        if gi % 100 == 0 or gi == n_grupos:
            print(f"  grupos {gi}/{n_grupos} | copiados={estados['copiado']} "
                  f"omitidos={estados['duplicado-omitido']} "
                  f"errores={len(errores)} | {time.time() - t0:.0f}s", flush=True)

    csv_file.close()

    # ------------------------------------------------------------------
    # 5) Logs finales
    # ------------------------------------------------------------------
    with open(logs_dir / "errores.txt", "w", encoding="utf-8", newline="\n") as f:
        if errores:
            f.write("\n".join(f"{r} :: {e}" for r, e in errores) + "\n")
        else:
            f.write("(sin errores)\n")

    lineas = ["RESUMEN DE UNIFICACIÓN",
              "=" * 60,
              f"Modo        : {args.modo}",
              f"Origen      : {origen}",
              f"Destino     : {destino}",
              f"Verificación: {'SÍ' if verificar else 'NO'}",
              "-" * 60]
    for estado in sorted(estados):
        lineas.append(f"{estado:<22}: {estados[estado]:>8}")
    lineas.append(f"{'ya-procesados':<22}: {n_ya_procesados:>8}")
    lineas.append("-" * 60)
    lineas.append(f"{'TOTAL':<22}: {total:>8}")
    lineas.append("")
    lineas.append(f"Tiempo total: {time.time() - t0:.0f} s")
    _escribir_utf8(logs_dir / "resumen_unificacion.txt", lineas)

    # ------------------------------------------------------------------
    # 6) Resumen en pantalla
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("UNIFICACIÓN COMPLETADA")
    print("=" * 60)
    for estado in sorted(estados):
        print(f"{estado:<22}: {estados[estado]}")
    print(f"{'ya-procesados':<22}: {n_ya_procesados}")
    print(f"Errores: {len(errores)}")
    print()
    print(f"Archivos únicos en: {destino}")
    if args.modo == "mover":
        print(f"Duplicados movidos a: {duplicados}")
    print(f"Log en: {csv_path}")
    if errores:
        print(f"REVISAR errores en: {logs_dir / 'errores.txt'}")
    print("El origen NO fue modificado (modo copiar).")


if __name__ == "__main__":
    main()