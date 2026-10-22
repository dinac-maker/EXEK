#!/usr/bin/env python3
"""Crea un componente nuevo en el almacén de un cliente a partir de la plantilla.

Uso:
    python herramientas/nuevo.py <cliente> <tipo> <id> [--nombre "Nombre"] [--autor correo]
    python herramientas/nuevo.py districash skill margen-por-linea --nombre "Margen por línea"

Tipos: skill, agente, artefacto, plugin.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import CARPETAS_TIPO, RAIZ  # noqa: E402

TIPO_A_CARPETA = {v: k for k, v in CARPETAS_TIPO.items()}


def correo_git() -> str:
    r = subprocess.run(["git", "config", "user.email"], cwd=RAIZ, capture_output=True, text=True)
    return r.stdout.strip() or "autor@exek.co"


def main() -> int:
    ap = argparse.ArgumentParser(description="Crea un componente desde la plantilla.")
    ap.add_argument("cliente")
    ap.add_argument("tipo", choices=sorted(TIPO_A_CARPETA))
    ap.add_argument("id")
    ap.add_argument("--nombre")
    ap.add_argument("--autor")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", args.id):
        print("El id solo admite minúsculas, números y guiones.")
        return 1
    dir_cliente = RAIZ / "clientes" / args.cliente
    if not (dir_cliente / "exek.yaml").exists():
        print(f"No existe el cliente '{args.cliente}' (falta clientes/{args.cliente}/exek.yaml).")
        return 1
    destino = dir_cliente / TIPO_A_CARPETA[args.tipo] / args.id
    if destino.exists():
        print(f"Ya existe {destino.relative_to(RAIZ)}.")
        return 1

    shutil.copytree(RAIZ / "plantillas" / args.tipo, destino)
    nombre = args.nombre or args.id.replace("-", " ").capitalize()
    autor = args.autor or correo_git()
    for archivo in destino.rglob("*"):
        if archivo.is_file():
            t = archivo.read_text(encoding="utf-8")
            t = t.replace("{{ID}}", args.id).replace("{{NOMBRE}}", nombre).replace("{{AUTOR}}", autor)
            archivo.write_text(t, encoding="utf-8")

    print(f"Creado {destino.relative_to(RAIZ)}")
    print("Siguiente paso: completa los textos entre [corchetes] y corre herramientas/validar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
