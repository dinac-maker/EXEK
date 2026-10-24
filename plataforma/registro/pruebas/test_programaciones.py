"""Pruebas de programaciones, ejecuciones y costos (fase 4), sin GCP."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from registro import calendario
from registro.almacen import AlmacenMemoria
from registro.carga_inicial import cargar
from registro.servicio import ErrorRegistro, Registro

EXEK = "dina.silva@exek.co"
BOG = ZoneInfo("America/Bogota")
UTC = dt.timezone.utc


def bog(*args) -> dt.datetime:
    """Hora de Bogotá convertida a UTC."""
    return dt.datetime(*args, tzinfo=BOG).astimezone(UTC)


LUNES_7 = {"frecuencia": "semanal", "dias": ["lun"], "hora": "07:00", "zona_horaria": "America/Bogota",
           "fecha_inicio": dt.date(2026, 10, 1), "fecha_fin": dt.date(2026, 12, 31), "activa": True}


# ---- calendario ---------------------------------------------------------------------

def test_semanal_en_hora_de_bogota():
    # Lunes 26/10/2026 07:00 en Bogotá = 12:00 UTC
    assert calendario.ocurrencias(LUNES_7, bog(2026, 10, 26, 0, 0), bog(2026, 10, 27, 0, 0)) == [bog(2026, 10, 26, 7, 0)]
    assert calendario.describir(LUNES_7) == "Lunes a las 07:00 (America/Bogota)"


def test_pendiente_una_sola_vez():
    momento = bog(2026, 10, 26, 7, 0)
    assert calendario.pendiente(LUNES_7, bog(2026, 10, 26, 6, 55), set()) is None  # todavía no
    assert calendario.pendiente(LUNES_7, bog(2026, 10, 26, 7, 5), set()) == momento
    assert calendario.pendiente(LUNES_7, bog(2026, 10, 26, 7, 20), {momento}) is None  # ya se corrió


def test_reloj_detenido_corre_una_vez_si_no_pasaron_24_horas():
    assert calendario.pendiente(LUNES_7, bog(2026, 10, 27, 6, 0), set()) == bog(2026, 10, 26, 7, 0)
    assert calendario.pendiente(LUNES_7, bog(2026, 10, 27, 8, 0), set()) is None


def test_fechas_de_inicio_y_fin_y_pausa():
    assert calendario.ocurrencias(LUNES_7, bog(2026, 9, 1, 0, 0), bog(2026, 9, 30, 23, 0)) == []  # antes del inicio
    assert calendario.ocurrencias(LUNES_7, bog(2027, 1, 1, 0, 0), bog(2027, 1, 31, 23, 0)) == []  # después del fin
    ultimo = calendario.ocurrencias(LUNES_7, bog(2026, 12, 1, 0, 0), bog(2026, 12, 31, 23, 0))[-1]
    assert ultimo == bog(2026, 12, 28, 7, 0)
    pausada = {**LUNES_7, "activa": False}
    assert calendario.pendiente(pausada, bog(2026, 10, 26, 7, 5), set()) is None
    assert calendario.proxima(pausada, bog(2026, 10, 26, 7, 5)) is None


def test_mensual_dia_31_en_febrero_y_cada_n_horas():
    mensual = {**LUNES_7, "frecuencia": "mensual", "dia_mes": 31, "fecha_fin": None, "fecha_inicio": dt.date(2027, 1, 1)}
    febrero = calendario.ocurrencias(mensual, bog(2027, 2, 1, 0, 0), bog(2027, 2, 28, 23, 0))
    assert febrero == [bog(2027, 2, 28, 7, 0)]
    horas = {**LUNES_7, "frecuencia": "horas", "cada_horas": 4, "hora": "08:00"}
    dia = calendario.ocurrencias(horas, bog(2026, 10, 27, 0, 0), bog(2026, 10, 27, 23, 59))
    assert [m.astimezone(BOG).hour for m in dia] == [8, 12, 16, 20]
    assert calendario.describir(horas) == "Cada 4 horas desde las 08:00 (America/Bogota)"


def test_proxima():
    assert calendario.proxima(LUNES_7, bog(2026, 10, 26, 7, 5)) == bog(2026, 11, 2, 7, 0)


# ---- programaciones en el registro --------------------------------------------------

@pytest.fixture
def reg():
    r = Registro(AlmacenMemoria())
    cargar(r)
    return r


def _monitor(reg, **cambios):
    datos = {"frecuencia": "semanal", "dias": ["lun"], "hora": "07:00", "fecha_inicio": dt.date(2026, 10, 1),
             "fecha_fin": dt.date(2026, 12, 31), "enviar_correo": True,
             "destinatarios": ["rol:comercial", "rol:gerencia"], **cambios}
    return reg.crear_programacion(EXEK, "districash", "monitor-clientes-perdidos", **datos)


def test_crear_programacion_del_monitor(reg):
    p = _monitor(reg)
    assert p["programacion_id"] == "monitor-clientes-perdidos-semanal"
    assert p["cron"] == "Lunes a las 07:00 (America/Bogota)"
    assert p["canales"] == ["portal", "correo"] and p["destinatarios"] == ["rol:comercial", "rol:gerencia"]
    sin_correo = reg.crear_programacion(EXEK, "districash", "tablero-control-gerencia", frecuencia="diaria",
                                        hora="06:00", fecha_inicio=dt.date(2026, 10, 25), enviar_correo=False)
    assert sin_correo["canales"] == ["portal"] and sin_correo["fecha_fin"] is None
    assert "con correo" in reg.historial("districash")[1]["detalle"]


def test_reglas_de_una_programacion(reg):
    with pytest.raises(ErrorRegistro, match="Solo los agentes y los artefactos"):
        reg.crear_programacion(EXEK, "districash", "indicadores-ventas", frecuencia="diaria", hora="06:00",
                               fecha_inicio=dt.date(2026, 10, 25))
    with pytest.raises(ErrorRegistro, match="anterior a la fecha de inicio"):
        _monitor(reg, fecha_fin=dt.date(2026, 9, 1))
    with pytest.raises(ErrorRegistro, match="al menos un rol o un correo"):
        _monitor(reg, destinatarios=[])
    with pytest.raises(ErrorRegistro, match="no es un correo de exek.co"):
        _monitor(reg, destinatarios=["alguien@gmail.com"])
    with pytest.raises(ErrorRegistro, match="rol ventas no existe"):
        _monitor(reg, destinatarios=["rol:ventas"])
    with pytest.raises(ErrorRegistro, match="HH:MM"):
        _monitor(reg, hora="7am")
    with pytest.raises(ErrorRegistro, match="día de la semana"):
        _monitor(reg, dias=[])


def test_pausar_y_cambiar(reg):
    p = _monitor(reg)
    p = reg.actualizar_programacion(EXEK, "districash", p["programacion_id"], p["revision"], activa=False,
                                    enviar_correo=False, destinatarios=[])
    assert p["activa"] is False and p["canales"] == ["portal"]
    reg.eliminar_programacion(EXEK, "districash", p["programacion_id"], p["revision"])
    assert reg.programaciones("districash") == []


def test_pendientes_y_ejecuciones(reg):
    p = _monitor(reg)
    ahora = bog(2026, 10, 26, 7, 5)
    pendientes = reg.programaciones_pendientes(ahora)
    assert [(x["programacion_id"], m) for x, m in pendientes] == [(p["programacion_id"], bog(2026, 10, 26, 7, 0))]
    e = reg.iniciar_ejecucion("districash", "programacion", componente_id="monitor-clientes-perdidos", tipo="agente",
                              version="0.2.0", programacion_id=p["programacion_id"], ocurrencia=pendientes[0][1])
    assert e["estado"] == "en_curso"
    assert reg.programaciones_pendientes(bog(2026, 10, 26, 7, 20)) == []  # no se corre dos veces
    e = reg.terminar_ejecucion(e, ok=True, resumen="1.561 clientes perdidos", resultado={"texto": "..."},
                               tokens={"entrada": 10, "salida": 300}, bytes_facturados=2**40 // 100,
                               costo_claude_usd=0.05, correo_enviado=True, correo_destinatarios=["a@exek.co"])
    assert e["estado"] == "terminada" and e["fin"] >= e["inicio"] and e["duracion_ms"] >= 0
    assert e["costo_bigquery_usd"] == pytest.approx(0.0625) and e["costo_total_usd"] == pytest.approx(0.1125)


def test_no_corre_lo_que_no_esta_publicado(reg):
    p = _monitor(reg)
    comp = reg.componente("districash", "monitor-clientes-perdidos")
    reg.retirar(EXEK, "districash", "monitor-clientes-perdidos", comp["revision"])
    assert reg.programaciones_pendientes(bog(2026, 10, 26, 7, 5)) == []


def test_costos_del_mes_por_cliente_componente_y_margen(reg):
    c = reg.cliente("districash")
    reg.actualizar_cliente(EXEK, "districash", c["revision"], margen_pct=0.3)
    e1 = reg.iniciar_ejecucion("districash", "programacion", componente_id="monitor-clientes-perdidos")
    reg.terminar_ejecucion(e1, ok=True, costo_claude_usd=0.05, bytes_facturados=0)
    e2 = reg.iniciar_ejecucion("districash", "eco", usuario="comercial.demo@exek.co")
    reg.terminar_ejecucion(e2, ok=True, costo_claude_usd=0.03, bytes_facturados=2**40 // 100)
    hoy = dt.datetime.now(BOG)
    [d] = reg.costos_del_mes(hoy.year, hoy.month)
    assert d["cliente_id"] == "districash" and d["ejecuciones"] == 2
    assert d["costo_directo"] == pytest.approx(0.05 + 0.03 + 0.0625, abs=1e-4)
    assert d["precio"] == pytest.approx(d["costo_directo"] * 1.3, abs=1e-4)
    assert set(d["por_componente"]) == {"monitor-clientes-perdidos", "Conversaciones con ECO"}
    assert set(d["por_disparador"]) == {"programacion", "eco"}
