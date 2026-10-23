"""Paquete del cliente para ECO.

Arma el paquete con herramientas/empaquetar.py (formato de plugin de Anthropic) y
lee de él lo que necesitan las herramientas de consulta: el SQL y los parámetros de
cada skill y las tablas declaradas en fuentes/.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from eco.configuracion import RAIZ, Cliente

sys.path.insert(0, str(RAIZ / "herramientas"))
from empaquetar import empaquetar  # noqa: E402


@dataclass
class SkillConsulta:
    id: str
    nombre: str
    version: str
    sql: str
    parametros: dict


@dataclass
class Paquete:
    ruta: Path
    nombre_plugin: str
    componentes: list[dict]
    skills: dict[str, SkillConsulta] = field(default_factory=dict)
    tablas_permitidas: set[str] = field(default_factory=set)

    def version_de(self, cid: str) -> str | None:
        for c in self.componentes:
            if c["id"] == cid:
                return c["version"]
        return None


def armar(cliente: Cliente, salida: Path | None = None) -> Paquete:
    """Modo prueba: el almacén tal como está en el repositorio (todas las versiones más nuevas)."""
    salida = salida or Path(tempfile.mkdtemp(prefix="eco-paquete-"))
    return cargar(empaquetar(cliente.carpeta, salida, None))


def cargar(ruta: Path) -> Paquete:
    """Lee un paquete ya armado (del repositorio o el publicado desde Cloud Storage)."""
    plugin = json.loads((ruta / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    manifiesto = json.loads((ruta / "exek" / "manifiesto.json").read_text(encoding="utf-8"))
    paquete = Paquete(ruta=ruta, nombre_plugin=plugin["name"], componentes=manifiesto["componentes"])

    for carpeta in sorted((ruta / "skills").glob("*")) if (ruta / "skills").is_dir() else []:
        ficha = yaml.safe_load((carpeta / "componente.yaml").read_text(encoding="utf-8"))
        consulta = (ficha.get("archivos") or {}).get("consulta")
        if not consulta:
            continue
        paquete.skills[ficha["id"]] = SkillConsulta(
            id=ficha["id"],
            nombre=ficha["nombre"],
            version=str(ficha["version"]),
            sql=(carpeta / consulta).read_text(encoding="utf-8"),
            parametros=ficha.get("parametros") or {},
        )

    for f in sorted((ruta / "exek" / "fuentes").glob("*.yaml")) if (ruta / "exek" / "fuentes").is_dir() else []:
        fuente = yaml.safe_load(f.read_text(encoding="utf-8"))
        if fuente.get("tipo") in ("tabla_bigquery", "vista_bigquery") and fuente.get("ubicacion"):
            paquete.tablas_permitidas.add(fuente["ubicacion"])
    return paquete
