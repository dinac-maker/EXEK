"""ECO como servicio web (Cloud Run).

    POST /preguntar   {"pregunta": "...", "usuario": "correo@cliente.com", "cliente": "districash"}
    GET  /salud

Cada llamada es una conversación nueva (sin seguimiento entre llamadas en la fase 2).
El servicio se despliega sin acceso público: solo entra quien tenga permiso en GCP.
"""
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from eco.configuracion import cargar_cliente
from eco.motor import SesionEco
from eco.paquete import Paquete, armar

CLIENTE_POR_DEFECTO = os.environ.get("ECO_CLIENTE", "districash")

app = FastAPI(title="ECO de prueba · I-NA")
_paquetes: dict[str, tuple] = {}


def _cliente_y_paquete(cliente_id: str) -> tuple:
    """El paquete se arma una vez por cliente y se reutiliza (solo se lee)."""
    if cliente_id not in _paquetes:
        cliente = cargar_cliente(cliente_id)
        _paquetes[cliente_id] = (cliente, armar(cliente))
    return _paquetes[cliente_id]


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=4000)
    usuario: str = Field(min_length=1, max_length=200)
    cliente: str = CLIENTE_POR_DEFECTO


@app.get("/salud")
def salud() -> dict:
    cliente, paquete = _cliente_y_paquete(CLIENTE_POR_DEFECTO)
    paquete: Paquete
    return {"estado": "ok", "cliente": cliente.cliente_id, "componentes": paquete.componentes}


@app.post("/preguntar")
async def preguntar(p: Pregunta) -> dict:
    try:
        cliente, paquete = _cliente_y_paquete(p.cliente)
    except SystemExit as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    async with SesionEco(cliente, paquete, p.usuario) as sesion:
        r = await sesion.preguntar(p.pregunta)
    return asdict(r)
