"""Pruebas del paquete publicado que usa ECO: solo versiones en producción y solo lo del rol."""
from __future__ import annotations

import json

import pytest

from registro.almacen import AlmacenMemoria
from registro.carga_inicial import cargar
from registro.paquetes import PaquetesLocal, armar_publicado
from registro.servicio import ErrorRegistro, Registro
from registro.sincronizar import respaldar_historial

EXEK = "dina.silva@exek.co"


@pytest.fixture
def entorno(tmp_path):
    reg = Registro(AlmacenMemoria())
    cargar(reg)
    paquetes = PaquetesLocal(tmp_path / "bucket")
    respaldar_historial(reg, paquetes, "districash")  # paquetes de cada commit, armados desde Git
    reg.crear_usuario(EXEK, "districash", "gerente.demo@exek.co", "gerencia")
    reg.crear_usuario(EXEK, "districash", "comercial.demo@exek.co", "comercial")
    reg.crear_usuario(EXEK, "districash", "compras.demo@exek.co", "compras")
    return reg, paquetes, tmp_path


def _armar(reg, paquetes, tmp_path, correo):
    a = reg.acceso_eco(correo)
    destino = armar_publicado("districash", a["elegidos"], a["publicados"], paquetes,
                              tmp_path / "cache", tmp_path / "salida" / correo)
    m = json.loads((destino / "exek" / "manifiesto.json").read_text(encoding="utf-8"))
    return destino, {c["id"]: c["version"] for c in m["componentes"]}


def test_gerencia_recibe_todo_lo_publicado(entorno):
    reg, paquetes, tmp = entorno
    destino, versiones = _armar(reg, paquetes, tmp, "gerente.demo@exek.co")
    # Cada componente en su versión publicada (no se fijan números: cambian con cada versión nueva).
    assert versiones == {c["componente_id"]: c["version_produccion"] for c in reg.publicados("districash")}
    assert set(versiones) == {"deteccion-clientes-perdidos", "indicadores-ventas",
                              "monitor-clientes-perdidos", "tablero-control-gerencia"}
    assert (destino / "skills" / "deteccion-clientes-perdidos" / "consulta.sql").exists()
    assert (destino / "agents" / "monitor-clientes-perdidos.md").exists()
    assert (destino / "exek" / "fuentes" / "ventas.yaml").exists()


def test_comercial_no_recibe_el_tablero(entorno):
    reg, paquetes, tmp = entorno
    destino, versiones = _armar(reg, paquetes, tmp, "comercial.demo@exek.co")
    assert "tablero-control-gerencia" not in versiones
    assert not (destino / "exek" / "artefactos" / "tablero-control-gerencia").exists()
    assert set(versiones) == {"deteccion-clientes-perdidos", "indicadores-ventas", "monitor-clientes-perdidos"}


def test_compras_no_recibe_nada(entorno):
    reg, paquetes, tmp = entorno
    _, versiones = _armar(reg, paquetes, tmp, "compras.demo@exek.co")
    assert versiones == {}


def test_volver_atras_cambia_lo_que_usa_eco(entorno):
    reg, paquetes, tmp = entorno
    comp = reg.componente("districash", "deteccion-clientes-perdidos")
    reg.publicar(EXEK, "districash", "deteccion-clientes-perdidos", "0.2.1", comp["revision"])
    destino, versiones = _armar(reg, paquetes, tmp, "comercial.demo@exek.co")
    assert versiones["deteccion-clientes-perdidos"] == "0.2.1"
    sql = (destino / "skills" / "deteccion-clientes-perdidos" / "consulta.sql").read_text(encoding="utf-8")
    assert sql.startswith("-- Districash · Detección de clientes perdidos · v0.2.1")


def test_un_agente_trae_las_skills_que_usa(entorno):
    reg, paquetes, tmp = entorno
    # Un rol que solo ve el agente (etiqueta Alertas) recibe también la skill que el agente usa.
    reg.crear_etiqueta(EXEK, "districash", "Alertas")
    agente = reg.componente("districash", "monitor-clientes-perdidos")
    reg.configurar_componente(EXEK, "districash", "monitor-clientes-perdidos", agente["revision"], etiquetas=["alertas"])
    reg.crear_rol(EXEK, "districash", "Alertas", ["alertas"])
    reg.crear_usuario(EXEK, "districash", "alertas.demo@exek.co", "alertas")
    _, versiones = _armar(reg, paquetes, tmp, "alertas.demo@exek.co")
    assert set(versiones) == {"monitor-clientes-perdidos", "deteccion-clientes-perdidos"}


def test_usuarios_sin_acceso(entorno):
    reg, _, _ = entorno
    with pytest.raises(ErrorRegistro, match="no está registrado"):
        reg.acceso_eco("nadie@exek.co")
    u = reg.usuario("compras.demo@exek.co")
    reg.actualizar_usuario(EXEK, u["correo"], u["revision"], estado="inactivo")
    with pytest.raises(ErrorRegistro, match="inactivo"):
        reg.acceso_eco("compras.demo@exek.co")
