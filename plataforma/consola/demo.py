"""Consola Exek en modo demostración: registro en memoria con Districash, sin tocar GCP.

Uso (desde la raíz del repositorio):
    python plataforma/consola/demo.py            abre en http://localhost:8081
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("CONSOLA_ALMACEN", "memoria")
os.environ.setdefault("CONSOLA_USUARIO_LOCAL", "dina.silva@exek.co")
os.environ.setdefault("CONSOLA_GITHUB", "apagado")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("consola.app:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8081")))
