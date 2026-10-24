"""Tareas de la fase 4: correr agentes y artefactos por programación o a mano.

Cada corrida queda en la tabla `ejecuciones` del registro con su inicio, fin, resultado y
costo, se envíe correo o no (el resultado se guarda siempre, para verlo en el portal).

- Agente: corre con el motor de ECO, en su versión publicada y con la cuenta del cliente.
  Recibe el resumen de la ejecución anterior para poder comparar.
- Artefacto (tablero): corre las consultas de sus skills y guarda una "foto" de los datos,
  sin Claude (más barato). El resumen sale de las tarjetas definidas en su tablero.yaml.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import traceback
from zoneinfo import ZoneInfo

import yaml

from eco import correo
from eco.acceso import AccesoRegistro, SinAcceso
from eco.consultas import ConsultasBigQuery
from eco.motor import SesionEco

USUARIO_RELOJ = "reloj"
FILAS_POR_SKILL = 60  # suficiente para 12+ meses de indicadores y la tabla de perdidos del tablero


def _bytes(consultas: list[dict]) -> int:
    return sum(c.get("bytes_facturados") or 0 for c in consultas if not c.get("rechazada"))


def destinatarios_de(reg, cliente_id: str, destinatarios: list[str]) -> list[str]:
    """rol:<id> -> correos de los usuarios activos con ese rol; los correos van tal cual."""
    usuarios = [u for u in reg.usuarios(cliente_id) if u["estado"] == "activo"]
    salida = set()
    for d in destinatarios or []:
        if d.startswith("rol:"):
            salida |= {u["correo"] for u in usuarios if u["rol_id"] == d[4:]}
        else:
            salida.add(d)
    return sorted(salida)


def _valor_para_tarjeta(foto: dict, indicador: str):
    """'indicadores-ventas.venta_neta_mes' -> valor de la fila más reciente de esa skill."""
    skill, _, columna = indicador.partition(".")
    filas = (foto.get(skill) or {}).get("filas") or []
    if not filas:
        return None
    fila = max(filas, key=lambda f: str(f.get("mes") or "")) if "mes" in filas[0] else filas[0]
    return fila.get(columna)


def _formato(valor) -> str:
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, float):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(valor)


def resumen_tablero(definicion: dict, foto: dict, nombres: dict[str, str] | None = None) -> str:
    """Texto corto del tablero: una línea por tarjeta con su valor más reciente.
    `nombres`: "skill.indicador" -> nombre del indicador según la ficha de la skill."""
    nombres = nombres or {}
    lineas = []
    for seccion in definicion.get("secciones") or []:
        for t in seccion.get("tarjetas") or []:
            valor = _valor_para_tarjeta(foto, t["indicador"])
            if valor is not None:
                nombre = nombres.get(t["indicador"]) or t["indicador"].split(".", 1)[1].replace("_", " ").capitalize()
                lineas.append(f"- **{nombre}:** {_formato(valor)}")
    corte = next((f.get("fecha_corte") for s in foto.values() for f in (s.get("filas") or [])[:1] if f.get("fecha_corte")), None)
    if corte and len(str(corte)) >= 10:
        anio, mes, dia = str(corte)[:10].split("-")
        corte = f"{dia}/{mes}/{anio}"
    titulo = definicion.get("titulo", "Tablero")
    return f"**{titulo}**" + (f" · datos al {corte}" if corte else "") + "\n" + "\n".join(lineas)


def _nombres_de_indicadores(paquete) -> dict[str, str]:
    nombres = {}
    for sid in paquete.skills:
        ficha = yaml.safe_load((paquete.ruta / "skills" / sid / "componente.yaml").read_text(encoding="utf-8"))
        for ind in ficha.get("indicadores") or []:
            nombres[f"{sid}.{ind['id']}"] = ind.get("nombre") or ind["id"]
    return nombres


def resumen_corto(texto: str) -> str:
    """Para listas y asuntos: el título de la alerta (primera línea con #) o su primera línea."""
    lineas = [linea.strip() for linea in (texto or "").splitlines() if linea.strip()]
    titulo = next((linea for linea in lineas if linea.startswith("#")), None) or (lineas[0] if lineas else "")
    return titulo.lstrip("#").replace("**", "").strip()[:300]


async def _correr_agente(cliente, paquete, comp, credenciales, cuenta, anterior: dict | None) -> dict:
    plugin = paquete.nombre_plugin
    instruccion = (
        f"Ejecuta ahora el agente «{comp['nombre']}» usando el agente {plugin}:{comp['componente_id']} y responde "
        "únicamente con el resultado que él prepare, completo y en el formato que indica.")
    if anterior and anterior.get("resultado"):
        try:
            previo = json.loads(anterior["resultado"]).get("texto", "")
        except (ValueError, AttributeError):
            previo = anterior["resultado"]
        instruccion += ("\n\nResultado de la ejecución anterior (" + anterior["inicio"].strftime("%d/%m/%Y") +
                        "), para comparar:\n" + previo[:6000])
    async with SesionEco(cliente, paquete, USUARIO_RELOJ, modo="produccion", rol=None, credenciales=credenciales,
                         cuenta_datos=cuenta) as sesion:
        r = await sesion.preguntar(instruccion)
    return {"ok": r.ok, "texto": r.texto, "error": r.error, "componentes": r.componentes, "consultas": r.consultas,
            "tokens": r.tokens, "costo": r.costo_usd_estimado}


def _correr_artefacto(cliente, paquete, comp, credenciales) -> dict:
    carpeta = paquete.ruta / "exek" / "artefactos" / comp["componente_id"]
    ficha = yaml.safe_load((carpeta / "componente.yaml").read_text(encoding="utf-8"))
    archivo = (ficha.get("archivos") or {}).get("definicion")
    definicion = yaml.safe_load((carpeta / archivo).read_text(encoding="utf-8")) if archivo else {}
    consultas = ConsultasBigQuery(cliente, paquete, credenciales)
    foto = {}
    for sid in ficha.get("usa_skills") or []:
        r = consultas.ejecutar_skill(sid, FILAS_POR_SKILL)
        foto[sid] = {"version": r["version"], "filas_total": r["filas_total"], "filas": r["filas"]}
    return {"ok": True, "texto": resumen_tablero(definicion, foto, _nombres_de_indicadores(paquete)), "foto": foto,
            "definicion": definicion,
            "consultas": consultas.consultas, "componentes": [{"id": s, "version": foto[s]["version"]} for s in foto]}


async def correr(acceso: AccesoRegistro, cliente_id: str, componente_id: str, *, disparador: str,
                 programacion: dict | None = None, ocurrencia: dt.datetime | None = None,
                 usuario: str | None = None) -> dict:
    """Corre un agente o artefacto publicado y deja la ejecución terminada en el registro."""
    reg = acceso.registro
    comp_registro = reg.componente(cliente_id, componente_id)
    ejecucion = reg.iniciar_ejecucion(
        cliente_id, disparador, componente_id=componente_id, tipo=comp_registro["tipo"],
        version=comp_registro["version_produccion"], programacion_id=(programacion or {}).get("programacion_id"),
        ocurrencia=ocurrencia, usuario=usuario)
    try:
        cliente, paquete, comp, credenciales, cuenta = acceso.para_componente(cliente_id, componente_id)
        if comp["tipo"] == "agente":
            previas = [e for e in reg.ejecuciones(cliente_id) if e["componente_id"] == componente_id
                       and e["estado"] == "terminada" and e["ejecucion_id"] != ejecucion["ejecucion_id"]]
            r = await _correr_agente(cliente, paquete, comp, credenciales, cuenta, previas[0] if previas else None)
            resultado = {"texto": r["texto"]}
        elif comp["tipo"] == "artefacto":
            r = await asyncio.to_thread(_correr_artefacto, cliente, paquete, comp, credenciales)
            resultado = {"texto": r["texto"], "foto": r["foto"], "definicion": r["definicion"]}
        else:
            raise SinAcceso(f"{comp['nombre']} no es un agente ni un artefacto.")
    except Exception as e:  # noqa: BLE001 - la ejecución queda con su error
        detalle = str(e) if isinstance(e, SinAcceso) else f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
        return reg.terminar_ejecucion(ejecucion, ok=False, error=detalle, resumen="No se pudo completar.")

    enviado, para, error_correo = None, [], None
    if r["ok"] and programacion and programacion.get("enviar_correo"):
        para = destinatarios_de(reg, cliente_id, programacion.get("destinatarios"))
        try:
            fecha = (ocurrencia or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(cliente.zona_horaria))
            correo.enviar(para, f"{comp['nombre']} · {cliente.nombre} · {fecha:%d/%m/%Y}", r["texto"], cliente.nombre)
            enviado = True
        except Exception as e:  # noqa: BLE001 - el resultado queda guardado aunque falle el correo
            enviado, error_correo = False, str(e)[:500]
    return reg.terminar_ejecucion(
        ejecucion, ok=r["ok"], resumen=resumen_corto(r["texto"]), resultado=resultado,
        error=r.get("error"), componentes=[f"{c['id']}@{c.get('version')}" for c in r.get("componentes") or []],
        modelo=cliente.modelo if comp["tipo"] == "agente" else None, tokens=r.get("tokens"),
        bytes_facturados=_bytes(r["consultas"]), costo_claude_usd=r.get("costo") if comp["tipo"] == "agente" else 0.0,
        correo_enviado=enviado, correo_destinatarios=para, correo_error=error_correo)


async def correr_pendientes(acceso: AccesoRegistro, ahora: dt.datetime | None = None) -> list[dict]:
    """Lo que hace el reloj cada 15 minutos: corre, una tras otra, las programaciones que tocan."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    salida = []
    for p, momento in acceso.registro.programaciones_pendientes(ahora):
        e = await correr(acceso, p["cliente_id"], p["componente_id"], disparador="programacion", programacion=p,
                         ocurrencia=momento)
        salida.append({"programacion_id": p["programacion_id"], "ejecucion_id": e["ejecucion_id"], "estado": e["estado"],
                       "correo_enviado": e["correo_enviado"]})
    return salida


def registrar_conversacion(reg, cliente_id: str, usuario: str, respuesta, modelo: str, inicio: dt.datetime) -> None:
    """Las conversaciones de ECO también cuentan en los costos del cliente (decisión F del 24/10/2026)."""
    reg.registrar_ejecucion_terminada(
        cliente_id, "eco", inicio, tipo="conversacion", usuario=usuario, ok=respuesta.ok, resumen=resumen_corto(respuesta.texto), error=respuesta.error,
        componentes=[f"{c['id']}@{c.get('version')}" for c in respuesta.componentes], modelo=modelo,
        tokens=respuesta.tokens, bytes_facturados=_bytes(respuesta.consultas),
        costo_claude_usd=respuesta.costo_usd_estimado)
