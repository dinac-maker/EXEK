"""Configuración de ECO: datos del cliente (exek.yaml) y de GCP.

Todo lo que cambia entre el computador del autor y Cloud Run se lee de variables
de entorno; lo propio de cada cliente se lee de su manifiesto en el repositorio.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]

# Proyecto de GCP donde corre ECO (Vertex AI) y región de los modelos Claude.
PROYECTO_ECO = os.environ.get("ECO_PROYECTO_GCP", "exekai")
REGION_VERTEX = os.environ.get("ECO_REGION_VERTEX", "global")

# Límites por respuesta, para que una pregunta no se alargue sin control.
MAX_TURNOS = int(os.environ.get("ECO_MAX_TURNOS", "25"))
PRESUPUESTO_USD = float(os.environ.get("ECO_PRESUPUESTO_USD", "2"))

# Filas que una consulta le devuelve a Claude como máximo (el total siempre se informa).
FILAS_POR_DEFECTO = 50
FILAS_MAXIMAS = 500

# Archivo JSONL del registro de ejecuciones (vacío = no se guarda en archivo).
REGISTRO = os.environ.get("ECO_REGISTRO", str(RAIZ / ".eco" / "ejecuciones.jsonl"))


@dataclass
class Cliente:
    cliente_id: str
    nombre: str
    carpeta: Path
    proyecto_datos: str
    proyecto_consultas: str
    modelo: str
    limite_bytes: int
    instrucciones: str
    zona_horaria: str
    moneda: str


def cargar_cliente(cliente_id: str) -> Cliente:
    carpeta = RAIZ / "clientes" / cliente_id
    ruta = carpeta / "exek.yaml"
    if not ruta.is_file():
        raise SystemExit(f"No existe el cliente '{cliente_id}' ({ruta})")
    m = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    gcp, eco = m.get("gcp") or {}, m.get("eco") or {}
    return Cliente(
        cliente_id=m["cliente_id"],
        nombre=m["nombre"],
        carpeta=carpeta,
        proyecto_datos=gcp["proyecto_datos"],
        proyecto_consultas=gcp["proyecto_consultas"],
        modelo=os.environ.get("ECO_MODELO") or eco["modelo_por_defecto"],
        limite_bytes=int(eco.get("limite_bytes_por_consulta") or 2_000_000_000),
        instrucciones=(eco.get("instrucciones_cliente") or "").strip(),
        zona_horaria=m.get("zona_horaria", "America/Bogota"),
        moneda=m.get("moneda", "COP"),
    )
