"""Pruebas de las tareas de la fase 4 (sin Claude, sin BigQuery y sin Gmail).

Uso (desde la carpeta plataforma/): python -m pytest eco/test_tareas.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from eco import acceso, correo, tareas
from eco.acceso import AccesoRegistro
from eco.consultas import ConsultasBigQuery
from registro.almacen import AlmacenMemoria
from registro.carga_inicial import cargar
from registro.paquetes import PaquetesLocal
from registro.servicio import Registro
from registro.sincronizar import respaldar_historial

EXEK = "dina.silva@exek.co"
BOG = ZoneInfo("America/Bogota")


def bog(*a):
    return dt.datetime(*a, tzinfo=BOG).astimezone(dt.timezone.utc)


@pytest.fixture
def eco(tmp_path, monkeypatch):
    monkeypatch.setattr(acceso, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("ECO_ACTUAR_COMO_CLIENTE", "0")
    monkeypatch.setenv("ECO_CORREO", "apagado")
    reg = Registro(AlmacenMemoria())
    cargar(reg)
    paquetes = PaquetesLocal(tmp_path / "bucket")
    respaldar_historial(reg, paquetes, "districash")
    reg.crear_usuario(EXEK, "districash", "gerente.demo@exek.co", "gerencia")
    reg.crear_usuario(EXEK, "districash", "comercial.demo@exek.co", "comercial")
    u = reg.crear_usuario(EXEK, "districash", "comercial.inactivo@exek.co", "comercial")
    reg.actualizar_usuario(EXEK, u["correo"], u["revision"], estado="inactivo")

    # BigQuery falso: cada skill devuelve dos filas y "factura" 1 MiB.
    def ejecutar_skill(self, skill_id, max_filas):
        filas = ([{"mes": "2026-02-01", "venta_neta_mes": 21952197493.0, "fecha_corte": "2026-03-31"},
                  {"mes": "2026-03-01", "venta_neta_mes": 27449812336.0, "clientes_activos": 5961, "fecha_corte": "2026-03-31"}]
                 if skill_id == "indicadores-ventas" else
                 [{"cliente": "83220|1", "clientes_perdidos": 1561, "valor_venta_perdido": 2227171160.0,
                   "perdidos_historico": 4697, "fecha_corte": "2026-03-31"}])
        self.consultas.append({"componente": skill_id, "bytes_facturados": 2**20, "filas_total": len(filas)})
        return {"skill": skill_id, "version": self.paquete.skills[skill_id].version, "filas_total": len(filas), "filas": filas}

    monkeypatch.setattr(ConsultasBigQuery, "ejecutar_skill", ejecutar_skill)

    # Agente falso: no llama a Claude.
    llamadas = []

    async def correr_agente(cliente, paquete, comp, credenciales, cuenta, anterior):
        llamadas.append({"comp": comp["componente_id"], "anterior": anterior})
        return {"ok": True, "texto": "**Clientes perdidos · datos al 31/03/2026**\n1.561 clientes perdidos.",
                "error": None, "componentes": [{"id": comp["componente_id"], "version": "0.2.0"}],
                "consultas": [{"bytes_facturados": 2**30}], "tokens": {"entrada": 10, "salida": 300}, "costo": 0.05}

    monkeypatch.setattr(tareas, "_correr_agente", correr_agente)
    return AccesoRegistro(reg, paquetes), reg, llamadas


def test_destinatarios_por_rol_solo_usuarios_activos(eco):
    _, reg, _ = eco
    assert tareas.destinatarios_de(reg, "districash", ["rol:comercial", "rol:gerencia", "otro@exek.co"]) == \
        ["comercial.demo@exek.co", "gerente.demo@exek.co", "otro@exek.co"]


def test_artefacto_guarda_la_foto_sin_claude(eco):
    acc, reg, _ = eco
    e = asyncio.run(tareas.correr(acc, "districash", "tablero-control-gerencia", disparador="manual", usuario=EXEK))
    assert e["estado"] == "terminada" and e["tipo"] == "artefacto" and e["inicio"] <= e["fin"]
    resultado = json.loads(e["resultado"])
    assert set(resultado["foto"]) == {"indicadores-ventas", "deteccion-clientes-perdidos"}
    assert "Venta neta del mes:** 27.449.812.336" in resultado["texto"]  # nombre de la ficha y fila más reciente
    assert "Clientes perdidos:** 1.561" in resultado["texto"]
    assert e["costo_claude_usd"] == 0 and e["bytes_facturados"] == 2 * 2**20
    assert e["correo_enviado"] is None  # sin programación no hay correo


def test_agente_programado_con_correo_apagado_guarda_el_resultado(eco):
    acc, reg, llamadas = eco
    p = reg.crear_programacion(EXEK, "districash", "monitor-clientes-perdidos", frecuencia="semanal", dias=["lun"],
                               hora="07:00", fecha_inicio=dt.date(2026, 10, 1), enviar_correo=True,
                               destinatarios=["rol:comercial"])
    hechas = asyncio.run(tareas.correr_pendientes(acc, bog(2026, 10, 26, 7, 5)))
    assert [h["programacion_id"] for h in hechas] == [p["programacion_id"]]
    e = reg.ejecuciones("districash")[0]
    assert e["estado"] == "terminada" and e["ocurrencia"] == bog(2026, 10, 26, 7, 0)
    assert json.loads(e["resultado"])["texto"].startswith("**Clientes perdidos")
    assert e["correo_enviado"] is False and "apagado" in e["correo_error"]  # el resultado igual quedó
    assert e["correo_destinatarios"] == ["comercial.demo@exek.co"]
    assert e["costo_claude_usd"] == 0.05 and e["costo_total_usd"] == pytest.approx(0.05 + 6.25 / 1024, abs=1e-6)
    # El reloj vuelve a pasar: no se repite; la semana siguiente el agente recibe el resultado anterior.
    assert asyncio.run(tareas.correr_pendientes(acc, bog(2026, 10, 26, 7, 20))) == []
    asyncio.run(tareas.correr_pendientes(acc, bog(2026, 11, 2, 7, 5)))
    assert llamadas[-1]["anterior"]["ejecucion_id"] == e["ejecucion_id"]


def test_si_falla_queda_la_ejecucion_con_error(eco):
    acc, reg, _ = eco
    comp = reg.componente("districash", "tablero-control-gerencia")
    reg.retirar(EXEK, "districash", "tablero-control-gerencia", comp["revision"])
    e = asyncio.run(tareas.correr(acc, "districash", "tablero-control-gerencia", disparador="manual", usuario=EXEK))
    assert e["estado"] == "error" and "no tiene una versión publicada" in e["error"] and e["fin"]


def test_conversacion_de_eco_cuenta_en_costos(eco):
    _, reg, _ = eco

    class Respuesta:
        ok, texto, error = True, "Febrero de 2026: $21.952.197.493", None
        componentes = [{"id": "indicadores-ventas", "version": "0.2.3"}]
        consultas, tokens, costo_usd_estimado = [{"bytes_facturados": 2**30}], {"entrada": 5}, 0.03

    inicio = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
    tareas.registrar_conversacion(reg, "districash", "comercial.demo@exek.co", Respuesta, "claude-sonnet-5-5", inicio)
    e = reg.ejecuciones("districash")[0]
    assert e["disparador"] == "eco" and e["tipo"] == "conversacion" and e["duracion_ms"] >= 5000
    hoy = dt.datetime.now(BOG)
    [costo] = reg.costos_del_mes(hoy.year, hoy.month)
    assert "Conversaciones con ECO" in costo["por_componente"]


def test_correo_en_html_con_tabla():
    texto = "**Resumen**\n- 1.561 clientes\n\n| Cliente | Días |\n|---|---|\n| 83220\\|1 | 102 |"
    html = correo.a_html(texto)
    assert "<b>Resumen</b>" in html and "<li>1.561 clientes</li>" in html and "<table" in html
    m = correo.armar_mensaje(["a@exek.co", "b@exek.co"], "Asunto ñ", texto, "Districash")
    assert m["To"] == "a@exek.co, b@exek.co" and "alertas@exek.co" in m["From"]
