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
import datetime as dt
import os
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from eco import tareas
from eco.acceso import AccesoRegistro, SinAcceso
from eco.configuracion import cargar_cliente
from eco.motor import SesionEco
from eco.paquete import Paquete, armar
from registro.servicio import ErrorRegistro

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
    inicio = dt.datetime.now(dt.timezone.utc)
    async with sesion_eco as sesion:
        r = await sesion.preguntar(p.pregunta)
    if p.modo == "produccion":
        # La conversación cuenta en los costos del cliente; si no se puede anotar, la respuesta igual sale.
        try:
            await asyncio.to_thread(tareas.registrar_conversacion, _registro().registro, at.cliente.cliente_id,
                                    at.usuario, r, at.cliente.modelo, inicio)
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo anotar la conversación como ejecución: {e}", flush=True)
    return asdict(r)


# ---- tareas programadas (fase 4) ------------------------------------------------------

@app.post("/programaciones/ejecutar-pendientes")
async def ejecutar_pendientes() -> dict:
    """La llama el reloj de Cloud Scheduler cada 15 minutos (cuenta reloj-exek, con permiso
    solo para llamar a este servicio)."""
    hechas = await tareas.correr_pendientes(_registro())
    return {"ejecutadas": len(hechas), "detalle": hechas}


class PedidoTarea(BaseModel):
    cliente_id: str = Field(min_length=1, max_length=63)
    componente_id: str = Field(min_length=1, max_length=63)
    usuario: str = Field(min_length=1, max_length=200)
    programacion_id: str | None = None
    enviar_correo: bool = False  # "Ejecutar ahora" no envía correo salvo que se pida


@app.post("/tareas/ejecutar")
async def ejecutar_tarea(p: PedidoTarea) -> dict:
    """"Ejecutar ahora" desde la Consola Exek. Corre el componente publicado y devuelve la
    ejecución terminada (puede tardar hasta un par de minutos en un agente)."""
    acceso = _registro()
    programacion = None
    if p.programacion_id:
        programacion = acceso.registro.almacen.obtener("programaciones", cliente_id=p.cliente_id,
                                                       programacion_id=p.programacion_id)
        if programacion is None:
            raise HTTPException(status_code=404, detail="No existe esa programación.")
        programacion = {**programacion, "enviar_correo": p.enviar_correo and programacion["enviar_correo"]}
    try:
        e = await tareas.correr(acceso, p.cliente_id, p.componente_id, disparador="manual", programacion=programacion,
                                usuario=p.usuario)
    except ErrorRegistro as err:
        raise HTTPException(status_code=404, detail=str(err)) from None
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in e.items()}
