"""Consola Exek: administración de clientes, roles, etiquetas, usuarios y almacenes.

Uso local (desde la carpeta plataforma/):
    uvicorn consola.app:app --reload --port 8081
    CONSOLA_ALMACEN=memoria uvicorn consola.app:app --port 8081    demostración sin GCP

En Cloud Run corre detrás de IAP (ver consola/identidad.py).
"""
from __future__ import annotations

import os
import time
import urllib.parse
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from consola import alta
from consola.identidad import usuario_actual
from registro.almacen import AlmacenBigQuery, AlmacenMemoria
from registro.paquetes import PaquetesGCS, PaquetesLocal
from registro.servicio import ErrorRegistro, Registro
from registro.sincronizar import sincronizar

AQUI = Path(__file__).resolve().parent
SINCRONIZAR_CADA = 120  # segundos entre lecturas de paquetes nuevos por cliente


def _crear_registro() -> tuple[Registro, object]:
    if os.environ.get("CONSOLA_ALMACEN") == "memoria":
        from registro.carga_inicial import cargar

        reg = Registro(AlmacenMemoria())
        cargar(reg)
        return reg, PaquetesLocal(Path(os.environ.get("CONSOLA_PAQUETES_LOCAL", AQUI / ".paquetes")))
    almacen = AlmacenBigQuery(os.environ.get("CONSOLA_PROYECTO", "exekai"),
                              os.environ.get("CONSOLA_DATASET", "exek_registro"))
    almacen.preparar()
    return Registro(almacen), PaquetesGCS(os.environ.get("CONSOLA_BUCKET", "exekai-paquetes"))


registro, paquetes = _crear_registro()
_ultima_sincronizacion: dict[str, float] = {}

app = FastAPI(title="Consola Exek", docs_url=None, redoc_url=None)
app.mount("/estaticos", StaticFiles(directory=AQUI / "estaticos"), name="estaticos")
plantillas = Jinja2Templates(directory=AQUI / "plantillas")
plantillas.env.filters["fecha"] = lambda d: d.astimezone().strftime("%d/%m/%Y %H:%M") if d else ""
plantillas.env.filters["iniciales"] = lambda correo: "".join(p[:1] for p in correo.split("@")[0].split(".")[:2]).upper()

ESTADOS_VERSION = {"en_produccion": "En producción", "en_prueba": "En prueba", "anterior": "Anterior",
                   "retirada": "Retirada"}
TIPOS = {"skill": "Skill", "agente": "Agente", "artefacto": "Artefacto", "plugin": "Plugin"}


def _ir(url: str, ok: str | None = None, error: str | None = None) -> RedirectResponse:
    q = {k: v for k, v in (("ok", ok), ("error", error)) if v}
    return RedirectResponse(url + ("?" + urllib.parse.urlencode(q) if q else ""), status_code=303)


def _pagina(request: Request, plantilla: str, quien: str, cliente_id: str | None = None, **datos):
    clientes = registro.clientes()
    actual = next((c for c in clientes if c["cliente_id"] == cliente_id), None) if cliente_id else None
    return plantillas.TemplateResponse(request, plantilla, {
        "quien": quien, "clientes": clientes, "cliente": actual, "ok": request.query_params.get("ok"),
        "error": request.query_params.get("error"), "TIPOS": TIPOS, "ESTADOS_VERSION": ESTADOS_VERSION, **datos})


def _sincronizar(cliente_id: str, forzar: bool = False) -> list:
    if not forzar and time.monotonic() - _ultima_sincronizacion.get(cliente_id, -1e9) < SINCRONIZAR_CADA:
        return []
    _ultima_sincronizacion[cliente_id] = time.monotonic()
    return sincronizar(registro, paquetes, cliente_id)


def _lista(valor: str | None) -> list[str]:
    return [x.strip() for x in (valor or "").replace(";", ",").split(",") if x.strip()]


# ---- inicio -----------------------------------------------------------------------

@app.get("/salud")
def salud():
    return {"estado": "ok"}


@app.get("/")
def inicio(quien: str = Depends(usuario_actual)):
    clientes = registro.clientes()
    return _ir(f"/c/{clientes[0]['cliente_id']}/almacen" if clientes else "/clientes")


# ---- almacén ----------------------------------------------------------------------

@app.get("/c/{cid}/almacen", response_class=HTMLResponse)
def almacen(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    try:
        registro.cliente(cid)
    except ErrorRegistro as e:
        return _ir("/clientes", error=str(e))
    aviso = None
    try:
        nuevas = _sincronizar(cid)
        if nuevas:
            aviso = "Versiones nuevas en prueba: " + ", ".join(f"{c} {n}" for c, n in nuevas)
    except Exception as e:  # noqa: BLE001 - la página se muestra igual
        aviso = f"No se pudieron leer los paquetes nuevos: {e}"
    etiquetas = {e["etiqueta_id"]: e["nombre"] for e in registro.etiquetas(cid)}
    filas = []
    for c in registro.componentes(cid):
        filas.append({**c, "en_prueba": registro.version_en_prueba(cid, c["componente_id"]),
                      "etiquetas_nombres": [etiquetas.get(e, e) for e in c["etiquetas"]]})
    return _pagina(request, "almacen.html", quien, cid, seccion="almacen", componentes=filas,
                   etiquetas=etiquetas, aviso=aviso)


@app.post("/c/{cid}/sincronizar")
def forzar_sincronizacion(cid: str, quien: str = Depends(usuario_actual)):
    try:
        nuevas = _sincronizar(cid, forzar=True)
    except Exception as e:  # noqa: BLE001
        return _ir(f"/c/{cid}/almacen", error=f"No se pudieron leer los paquetes: {e}")
    return _ir(f"/c/{cid}/almacen", ok=f"{len(nuevas)} versiones nuevas" if nuevas else "No hay versiones nuevas")


@app.get("/c/{cid}/componentes/{comp}", response_class=HTMLResponse)
def componente(request: Request, cid: str, comp: str, quien: str = Depends(usuario_actual)):
    try:
        c = registro.componente(cid, comp)
        versiones = registro.versiones(cid, comp)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/almacen", error=str(e))
    return _pagina(request, "componente.html", quien, cid, seccion="almacen", comp=c, versiones=versiones,
                   etiquetas=registro.etiquetas(cid))


@app.post("/c/{cid}/componentes/{comp}/publicar")
def publicar(cid: str, comp: str, numero: str = Form(...), revision: int = Form(...),
             quien: str = Depends(usuario_actual)):
    try:
        registro.publicar(quien, cid, comp, numero, revision)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/componentes/{comp}", error=str(e))
    return _ir(f"/c/{cid}/componentes/{comp}", ok=f"Versión {numero} en producción")


@app.post("/c/{cid}/componentes/{comp}/retirar")
def retirar(cid: str, comp: str, revision: int = Form(...), quien: str = Depends(usuario_actual)):
    try:
        registro.retirar(quien, cid, comp, revision)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/componentes/{comp}", error=str(e))
    return _ir(f"/c/{cid}/componentes/{comp}", ok="Componente retirado: ECO ya no lo usa")


@app.post("/c/{cid}/componentes/{comp}/configurar")
async def configurar(request: Request, cid: str, comp: str, quien: str = Depends(usuario_actual)):
    form = await request.form()
    try:
        registro.configurar_componente(quien, cid, comp, int(form["revision"]),
                                       etiquetas=form.getlist("etiquetas"),
                                       visible_portal=form.get("visible_portal") == "si")
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/componentes/{comp}", error=str(e))
    return _ir(f"/c/{cid}/componentes/{comp}", ok="Cambios guardados")


# ---- clientes ---------------------------------------------------------------------

@app.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request, quien: str = Depends(usuario_actual)):
    return _pagina(request, "clientes.html", quien, request.query_params.get("c"), seccion="clientes")


@app.post("/clientes")
def crear_cliente(nombre: str = Form(""), dominios: str = Form(""), proyecto_datos: str = Form(""),
                  dataset: str = Form(""), quien: str = Depends(usuario_actual)):
    try:
        c = registro.crear_cliente(quien, nombre, _lista(dominios), proyecto_datos, dataset)
    except ErrorRegistro as e:
        return _ir("/clientes", error=str(e))
    try:
        url = alta.crear_solicitud(c, quien)
        registro._anotar(quien, "cliente", "solicitud", f"Solicitud de cambio con la carpeta del cliente: {url}",
                         c["cliente_id"], c["cliente_id"], despues={"solicitud": url})
        return _ir(f"/clientes/{c['cliente_id']}/alta", ok="Cliente registrado y solicitud de cambio creada")
    except Exception as e:  # noqa: BLE001 - el cliente ya quedó registrado; se puede reintentar
        return _ir(f"/clientes/{c['cliente_id']}/alta", error=f"Cliente registrado, pero no se pudo crear la solicitud de cambio: {e}")


@app.get("/clientes/{cid}/alta", response_class=HTMLResponse)
def ver_alta(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    try:
        c = registro.cliente(cid)
    except ErrorRegistro as e:
        return _ir("/clientes", error=str(e))
    solicitud = next((h["detalle"].split(": ", 1)[-1] for h in registro.historial(cid) if h["accion"] == "solicitud"), None)
    return _pagina(request, "alta.html", quien, cid, seccion="clientes", c=c, comandos=alta.comandos_guiados(c),
                   solicitud=solicitud)


@app.post("/clientes/{cid}/solicitud")
def reintentar_solicitud(cid: str, quien: str = Depends(usuario_actual)):
    c = registro.cliente(cid)
    try:
        url = alta.crear_solicitud(c, quien)
    except Exception as e:  # noqa: BLE001
        return _ir(f"/clientes/{cid}/alta", error=f"No se pudo crear la solicitud de cambio: {e}")
    registro._anotar(quien, "cliente", "solicitud", f"Solicitud de cambio con la carpeta del cliente: {url}", cid, cid,
                     despues={"solicitud": url})
    return _ir(f"/clientes/{cid}/alta", ok="Solicitud de cambio creada")


@app.post("/clientes/{cid}/verificar")
def verificar(cid: str, quien: str = Depends(usuario_actual)):
    c = registro.cliente(cid)
    bien, mensaje = alta.verificar_acceso(c)
    if bien != bool(c["acceso_verificado"]):
        registro.actualizar_cliente(quien, cid, c["revision"], acceso_verificado=bien)
    return _ir(f"/clientes/{cid}/alta", ok=mensaje) if bien else _ir(f"/clientes/{cid}/alta", error=mensaje)


@app.post("/clientes/{cid}/editar")
def editar_cliente(cid: str, revision: int = Form(...), nombre: str = Form(...), dominios: str = Form(...),
                   proyecto_datos: str = Form(...), dataset: str = Form(...), estado: str = Form("activo"),
                   quien: str = Depends(usuario_actual)):
    try:
        actual = registro.cliente(cid)
        cambios = {k: v for k, v in {"nombre": nombre.strip(), "dominios": _lista(dominios),
                                     "proyecto_datos": proyecto_datos.strip(), "dataset": dataset.strip(),
                                     "estado": estado}.items() if v != actual[k]}
        if cambios:
            registro.actualizar_cliente(quien, cid, revision, **cambios)
    except ErrorRegistro as e:
        return _ir(f"/clientes/{cid}/alta", error=str(e))
    return _ir(f"/clientes/{cid}/alta", ok="Cambios guardados" if cambios else "No había cambios")


# ---- etiquetas y roles ------------------------------------------------------------

@app.get("/c/{cid}/roles", response_class=HTMLResponse)
def roles(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    etiquetas = registro.etiquetas(cid)
    nombres = {e["etiqueta_id"]: e["nombre"] for e in etiquetas}
    publicados = registro.publicados(cid)
    filas = [{**r, "etiquetas_nombres": [nombres.get(e, e) for e in r["etiquetas"]],
              "ve": len(registro.permitidos_para_rol(cid, r["rol_id"]))} for r in registro.roles(cid)]
    return _pagina(request, "roles.html", quien, cid, seccion="roles", etiquetas=etiquetas, roles=filas,
                   total_publicados=len(publicados))


@app.post("/c/{cid}/etiquetas")
def crear_etiqueta(cid: str, nombre: str = Form(""), quien: str = Depends(usuario_actual)):
    try:
        registro.crear_etiqueta(quien, cid, nombre)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/roles", error=str(e))
    return _ir(f"/c/{cid}/roles", ok=f"Etiqueta {nombre.strip()} creada")


@app.post("/c/{cid}/etiquetas/{eid}")
def editar_etiqueta(cid: str, eid: str, revision: int = Form(...), nombre: str = Form(""),
                    accion: str = Form("renombrar"), quien: str = Depends(usuario_actual)):
    try:
        if accion == "eliminar":
            registro.eliminar_etiqueta(quien, cid, eid, revision)
            return _ir(f"/c/{cid}/roles", ok="Etiqueta eliminada")
        registro.renombrar_etiqueta(quien, cid, eid, nombre, revision)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/roles", error=str(e))
    return _ir(f"/c/{cid}/roles", ok="Etiqueta renombrada")


@app.post("/c/{cid}/roles")
async def crear_rol(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    form = await request.form()
    try:
        registro.crear_rol(quien, cid, form.get("nombre", ""), form.getlist("etiquetas"), form.get("descripcion") or None)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/roles", error=str(e))
    return _ir(f"/c/{cid}/roles", ok="Rol creado")


@app.post("/c/{cid}/roles/{rid}")
async def editar_rol(request: Request, cid: str, rid: str, quien: str = Depends(usuario_actual)):
    form = await request.form()
    try:
        registro.actualizar_rol(quien, cid, rid, int(form["revision"]), etiquetas=form.getlist("etiquetas"),
                                descripcion=form.get("descripcion"))
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/roles", error=str(e))
    return _ir(f"/c/{cid}/roles", ok="Rol actualizado")


# ---- usuarios ---------------------------------------------------------------------

@app.get("/c/{cid}/usuarios", response_class=HTMLResponse)
def usuarios(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    roles_ = {r["rol_id"]: r["nombre"] for r in registro.roles(cid)}
    return _pagina(request, "usuarios.html", quien, cid, seccion="usuarios", usuarios=registro.usuarios(cid),
                   roles=roles_)


@app.post("/c/{cid}/usuarios")
def crear_usuario(cid: str, correo: str = Form(""), nombre: str = Form(""), rol_id: str = Form(""),
                  quien: str = Depends(usuario_actual)):
    try:
        registro.crear_usuario(quien, cid, correo, rol_id, nombre)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/usuarios", error=str(e))
    return _ir(f"/c/{cid}/usuarios", ok=f"Usuario {correo.strip().lower()} agregado")


@app.post("/c/{cid}/usuarios/{correo}")
def editar_usuario(cid: str, correo: str, revision: int = Form(...), rol_id: str = Form(...),
                   estado: str = Form(...), nombre: str = Form(""), quien: str = Depends(usuario_actual)):
    try:
        registro.actualizar_usuario(quien, correo, revision, rol_id=rol_id, estado=estado, nombre=nombre)
    except ErrorRegistro as e:
        return _ir(f"/c/{cid}/usuarios", error=str(e))
    return _ir(f"/c/{cid}/usuarios", ok=f"Usuario {correo} actualizado")


# ---- historial --------------------------------------------------------------------

@app.get("/c/{cid}/historial", response_class=HTMLResponse)
def historial(request: Request, cid: str, quien: str = Depends(usuario_actual)):
    return _pagina(request, "historial.html", quien, cid, seccion="historial", historial=registro.historial(cid))
