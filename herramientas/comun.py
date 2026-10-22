"""Funciones compartidas por las herramientas del almacén de componentes."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
ESQUEMAS = RAIZ / "esquemas"

# Carpeta del almacén -> tipo de componente
CARPETAS_TIPO = {
    "skills": "skill",
    "agentes": "agente",
    "artefactos": "artefacto",
    "plugins": "plugin",
}

PATRON_TABLA_SQL = re.compile(r"`([a-z0-9-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+)`")
PATRON_PARAMETRO_SQL = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")


def leer_yaml(ruta: Path):
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def leer_esquema(nombre: str) -> dict:
    with open(ESQUEMAS / nombre, encoding="utf-8") as f:
        return json.load(f)


def leer_frontmatter(ruta: Path) -> tuple[dict | None, str]:
    """Devuelve (encabezado YAML, cuerpo) de un archivo Markdown con encabezado ---."""
    texto = ruta.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        return None, texto
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return None, texto
    return yaml.safe_load(partes[1]) or {}, partes[2]


def componentes(dir_cliente: Path):
    """Itera (tipo, carpeta) de cada componente del almacén."""
    for carpeta, tipo in CARPETAS_TIPO.items():
        base = dir_cliente / carpeta
        if not base.is_dir():
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            yield tipo, sub


def tablas_en_sql(sql: str) -> set[str]:
    sin_comentarios = re.sub(r"--[^\n]*", "", sql)
    return set(PATRON_TABLA_SQL.findall(sin_comentarios))


def parametros_en_sql(sql: str) -> set[str]:
    sin_comentarios = re.sub(r"--[^\n]*", "", sql)
    return set(PATRON_PARAMETRO_SQL.findall(sin_comentarios))
