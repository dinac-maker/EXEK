#!/usr/bin/env python3
"""Arma el paquete del cliente: su almacén en formato de plugin de Anthropic.

Uso:
    python herramientas/empaquetar.py clientes/<cliente> [--salida dist] [--componentes id1,id2] [--zip]

Resultado (dist/<cliente>/):
    .claude-plugin/plugin.json      manifiesto del plugin (lo lee el Agent SDK de Claude)
    skills/<id>/                    SKILL.md, consulta.sql y componente.yaml de cada skill
    agents/<id>.md                  instrucciones de cada agente (formato subagente)
    exek/manifiesto.json            componentes, versiones y dependencias (lo lee la plataforma)
    exek/fuentes/                   fuentes de datos
    exek/artefactos/<id>/           definiciones de los artefactos
    exek/plugins/<id>/              conectores (los ejecuta la plataforma, no ECO)

Con --componentes se incluyen solo esos componentes (la publicación desde la Consola
Exek usará esta opción con las versiones en producción). Las skills de las que dependen
se agregan automáticamente.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import RAIZ, componentes, leer_yaml  # noqa: E402


def commit_actual() -> str | None:
    """Commit de Git del almacén. Donde no hay Git (por ejemplo, la imagen de ECO) se usa GIT_COMMIT."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True)
    except OSError:
        return os.environ.get("GIT_COMMIT") or None
    return r.stdout.strip() or os.environ.get("GIT_COMMIT") or None


def cerrar_dependencias(elegidos: set[str], fichas: dict) -> set[str]:
    pendientes = list(elegidos)
    while pendientes:
        cid = pendientes.pop()
        for s in fichas.get(cid, {}).get("usa_skills") or []:
            if s not in elegidos:
                elegidos.add(s)
                pendientes.append(s)
    return elegidos


def empaquetar(dir_cliente: Path, salida: Path, solo: set[str] | None) -> Path:
    dir_cliente = dir_cliente.resolve()
    manifiesto = leer_yaml(dir_cliente / "exek.yaml")
    cliente_id = manifiesto["cliente_id"]

    fichas, carpetas = {}, {}
    for tipo, carpeta in componentes(dir_cliente):
        ficha = leer_yaml(carpeta / "componente.yaml")
        fichas[ficha["id"]] = ficha
        carpetas[ficha["id"]] = carpeta

    incluir = set(fichas)
    if solo:
        faltan = solo - set(fichas)
        if faltan:
            raise SystemExit(f"No existen en el almacén: {', '.join(sorted(faltan))}")
        incluir = cerrar_dependencias(set(solo), fichas)

    destino = (salida / cliente_id).resolve()
    if destino.exists():
        shutil.rmtree(destino)
    (destino / ".claude-plugin").mkdir(parents=True)
    (destino / "exek").mkdir()

    generado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = commit_actual()

    for cid in sorted(incluir):
        ficha, carpeta = fichas[cid], carpetas[cid]
        tipo = ficha["tipo"]
        if tipo == "skill":
            shutil.copytree(carpeta, destino / "skills" / cid)
        elif tipo == "agente":
            (destino / "agents").mkdir(exist_ok=True)
            shutil.copy(carpeta / ficha["archivos"]["instrucciones"], destino / "agents" / f"{cid}.md")
            (destino / "exek" / "agentes").mkdir(exist_ok=True)
            shutil.copy(carpeta / "componente.yaml", destino / "exek" / "agentes" / f"{cid}.yaml")
        elif tipo == "artefacto":
            shutil.copytree(carpeta, destino / "exek" / "artefactos" / cid)
        elif tipo == "plugin":
            shutil.copytree(carpeta, destino / "exek" / "plugins" / cid)

    if (dir_cliente / "fuentes").is_dir():
        shutil.copytree(dir_cliente / "fuentes", destino / "exek" / "fuentes")

    plugin_json = {
        "name": f"exek-{cliente_id}",
        "version": f"{generado[:10].replace('-', '.')}+{commit or 'local'}",
        "description": f"Componentes de {manifiesto['nombre']} para ECO (I-NA · Exek)",
        "author": {"name": "Exek"},
    }
    (destino / ".claude-plugin" / "plugin.json").write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2), encoding="utf-8")

    exek_json = {
        "cliente_id": cliente_id,
        "nombre": manifiesto["nombre"],
        "generado": generado,
        "commit": commit,
        "eco": manifiesto.get("eco", {}),
        "gcp": manifiesto.get("gcp", {}),
        "zona_horaria": manifiesto.get("zona_horaria"),
        "moneda": manifiesto.get("moneda"),
        "componentes": [
            {
                "id": cid,
                "tipo": fichas[cid]["tipo"],
                "nombre": fichas[cid]["nombre"],
                "version": fichas[cid]["version"],
                "usa_skills": fichas[cid].get("usa_skills", []),
                "fuentes": fichas[cid].get("fuentes", []),
            }
            for cid in sorted(incluir)
        ],
    }
    (destino / "exek" / "manifiesto.json").write_text(json.dumps(exek_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description="Arma el paquete del cliente en formato de plugin de Anthropic.")
    ap.add_argument("cliente", type=Path)
    ap.add_argument("--salida", type=Path, default=RAIZ / "dist")
    ap.add_argument("--componentes", help="ids separados por comas; por defecto, todos")
    ap.add_argument("--zip", action="store_true", help="Además, comprime el paquete")
    args = ap.parse_args()

    solo = set(args.componentes.split(",")) if args.componentes else None
    destino = empaquetar(args.cliente, args.salida, solo)
    print(f"Paquete listo en {destino}")
    for p in sorted(destino.rglob("*")):
        if p.is_file():
            print("  ", p.relative_to(destino))
    if args.zip:
        archivo = shutil.make_archive(str(destino), "zip", destino)
        print(f"Comprimido en {archivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
