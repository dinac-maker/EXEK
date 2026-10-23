"""ECO como servicio web (Cloud Run).

    POST /preguntar   {"pregunta": "...", "usuario": "correo@cliente.com"}
                      {"pregunta": "...", "usuario": "...", "modo": "prueba", "cliente": "districash"}
    GET  /salud

Modo "produccion" (por defecto): el usuario debe estar registrado en la Consola Exek; ECO
usa solo las versiones publicadas de los componentes de su rol y consulta los datos con
la cuenta de su cliente. Modo "prueba": el almacén del repositorio completo, para Exek.
Cada llamada es una conversación nueva.
El servicio se despliega sin acceso público: solo entra quien tenga permiso en GCP.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from eco.acceso import AccesoRegistro, SinAcceso
from eco.configuracion import cargar_cliente
from eco.motor import SesionEco
from eco.paquete import Paquete, armar

CLIENTE_POR_DEFECTO = os.environ.get("ECO_CLIENTE", "districash")

app = FastAPI(title="ECO de prueba · I-NA")
_paquetes: dict[str, tuple] = {}
_acceso: AccesoRegistro | None = None


def _registro() -> AccesoRegistro:
    global _acceso
    if _acceso is None:
        _acceso = AccesoRegistro()
    return _acceso


def _cliente_y_paquete(cliente_id: str) -> tuple:
    """El paquete se arma una vez por cliente y se reutiliza (solo se lee)."""
    if cliente_id not in _paquetes:
        cliente = cargar_cliente(cliente_id)
        _paquetes[cliente_id] = (cliente, armar(cliente))
    return _paquetes[cliente_id]


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=4000)
    usuario: str = Field(min_length=1, max_length=200)
    modo: Literal["produccion", "prueba"] = "produccion"
    cliente: str = CLIENTE_POR_DEFECTO  # solo en modo prueba; en producción sale del registro


@app.get("/salud")
def salud() -> dict:
    cliente, paquete = _cliente_y_paquete(CLIENTE_POR_DEFECTO)
    paquete: Paquete
    return {"estado": "ok", "cliente": cliente.cliente_id, "componentes": paquete.componentes}


@app.post("/preguntar")
async def preguntar(p: Pregunta) -> dict:
    if p.modo == "produccion":
        try:
            at = await asyncio.to_thread(_registro().atender, p.usuario)
        except SinAcceso as e:
            return {"texto": str(e), "ok": False, "sesion_id": None, "componentes": [], "consultas": [],
                    "tokens": {}, "costo_usd_estimado": None, "duracion_ms": 0, "error": "sin_acceso"}
        sesion_eco = SesionEco(at.cliente, at.paquete, at.usuario, modo="produccion", rol=at.rol,
                               credenciales=at.credenciales, cuenta_datos=at.cuenta_datos)
    else:
        try:
            cliente, paquete = _cliente_y_paquete(p.cliente)
        except SystemExit as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        sesion_eco = SesionEco(cliente, paquete, p.usuario)
    async with sesion_eco as sesion:
        r = await sesion.preguntar(p.pregunta)
    return asdict(r)
