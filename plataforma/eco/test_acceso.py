"""Pruebas de ECO en modo producción (sin llamar a Claude ni a GCP).

Uso (desde la carpeta plataforma/): python -m pytest eco/test_acceso.py
"""
from __future__ import annotations

import pytest

from eco import acceso
from eco.acceso import AccesoRegistro, SinAcceso
from registro.almacen import AlmacenMemoria
from registro.carga_inicial import cargar
from registro.paquetes import PaquetesLocal
from registro.servicio import Registro
from registro.sincronizar import respaldar_historial

EXEK = "dina.silva@exek.co"


@pytest.fixture
def eco(tmp_path, monkeypatch):
    monkeypatch.setattr(acceso, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("ECO_ACTUAR_COMO_CLIENTE", "0")
    reg = Registro(AlmacenMemoria())
    cargar(reg)
    paquetes = PaquetesLocal(tmp_path / "bucket")
    respaldar_historial(reg, paquetes, "districash")
    reg.crear_usuario(EXEK, "districash", "comercial.demo@exek.co", "comercial")
    reg.crear_usuario(EXEK, "districash", "compras.demo@exek.co", "compras")
    return AccesoRegistro(reg, paquetes), reg


def test_comercial_recibe_su_paquete_publicado(eco):
    acc, _ = eco
    at = acc.atender("Comercial.Demo@exek.co")
    assert at.rol == "comercial" and at.cliente.cliente_id == "districash"
    ids = {c["id"] for c in at.paquete.componentes}
    assert ids == {"deteccion-clientes-perdidos", "indicadores-ventas", "monitor-clientes-perdidos"}
    assert set(at.paquete.skills) == {"deteccion-clientes-perdidos", "indicadores-ventas"}
    assert at.paquete.tablas_permitidas == {"exek-produccion.NewtonAgentSpace.AgentspaceVentas"}
    assert at.credenciales is None  # fuera de Cloud Run, sin ECO_ACTUAR_COMO_CLIENTE=1


def test_el_paquete_se_reutiliza_y_cambia_al_publicar(eco):
    acc, reg = eco
    primero = acc.atender("comercial.demo@exek.co").paquete
    assert acc.atender("comercial.demo@exek.co").paquete is primero
    comp = reg.componente("districash", "deteccion-clientes-perdidos")
    reg.publicar(EXEK, "districash", "deteccion-clientes-perdidos", "0.2.1", comp["revision"])
    acc._accesos.clear()  # en producción esto pasa solo al vencer la vigencia (5 minutos)
    nuevo = acc.atender("comercial.demo@exek.co").paquete
    assert nuevo is not primero
    assert nuevo.skills["deteccion-clientes-perdidos"].version == "0.2.1"


def test_sin_acceso(eco):
    acc, _ = eco
    with pytest.raises(SinAcceso, match="no está registrado"):
        acc.atender("nadie@exek.co")
    with pytest.raises(SinAcceso, match="no tiene componentes publicados"):
        acc.atender("compras.demo@exek.co")
