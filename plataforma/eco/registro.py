"""Registro de ejecuciones de ECO.

Cada respuesta deja una línea JSON con cliente, usuario, componentes usados, consultas,
tokens, costo estimado y resultado. Por ahora se guarda en un archivo JSONL
(decisión D, 22/10/2026); en Cloud Run además se escribe en la salida estándar, que
llega a Cloud Logging.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from eco.configuracion import REGISTRO

# En Cloud Run existe K_SERVICE; ahí la salida estándar va a Cloud Logging.
EN_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))


def escribir(ejecucion: dict) -> None:
    linea = json.dumps(ejecucion, ensure_ascii=False, default=str)
    if REGISTRO:
        ruta = Path(REGISTRO)
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError as e:
            print(f"No se pudo escribir el registro en {ruta}: {e}", file=sys.stderr)
    if EN_CLOUD_RUN:
        print(json.dumps({"severity": "INFO", "message": "eco.ejecucion", "ejecucion": ejecucion},
                         ensure_ascii=False, default=str), flush=True)
