"""Pruebas de las versiones guardadas por commit (sin GCP: carpeta local en lugar del bucket)."""
from __future__ import annotations

import json

import pytest

from registro.almacen import AlmacenMemoria
from registro.carga_inicial import cargar
from registro.paquetes import PaquetesLocal, armar_desde_git
from registro.servicio import Registro
from registro.sincronizar import respaldar_historial, sincronizar


@pytest.fixture
def reg():
    r = Registro(AlmacenMemoria())
    cargar(r)
    return r


def _manifiesto(commit, generado, version):
    return {"cliente_id": "districash", "commit": commit, "generado": generado, "componentes": [
        {"id": "deteccion-clientes-perdidos", "tipo": "skill", "nombre": "Detección de clientes perdidos",
         "version": version, "notas_version": "Nueva ventana de días", "autor": "dina.silva@exek.co"},
        {"id": "indicadores-ventas", "tipo": "skill", "nombre": "Indicadores de ventas",
         "version": "0.2.2", "notas_version": None, "autor": "dina.silva@exek.co"}]}


def _dejar(paquetes, tmp_path, manifiesto):
    zip_falso = tmp_path / "p.zip"
    zip_falso.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # zip vacío válido
    paquetes.subir("districash", manifiesto["commit"], zip_falso, manifiesto)


def test_sincronizar_registra_solo_lo_nuevo(reg, tmp_path):
    publicada = reg.componente("districash", "deteccion-clientes-perdidos")["version_produccion"]
    paquetes = PaquetesLocal(tmp_path / "bucket")
    _dejar(paquetes, tmp_path, _manifiesto("aaa1111", "2026-10-24T10:00:00Z", "9.0.0"))
    assert sincronizar(reg, paquetes, "districash") == [("deteccion-clientes-perdidos", "9.0.0")]
    assert sincronizar(reg, paquetes, "districash") == []  # repetir no duplica
    v = next(v for v in reg.versiones("districash", "deteccion-clientes-perdidos") if v["numero"] == "9.0.0")
    assert v["estado"] == "en_prueba" and v["commit"] == "aaa1111" and v["registrada_por"] == "GitHub"
    assert v["paquete_uri"].endswith("aaa1111.zip")
    # La versión publicada no cambia hasta que alguien la publica.
    assert reg.componente("districash", "deteccion-clientes-perdidos")["version_produccion"] == publicada


def test_la_version_toma_el_primer_commit_en_que_aparecio(reg, tmp_path):
    paquetes = PaquetesLocal(tmp_path / "bucket")
    _dejar(paquetes, tmp_path, _manifiesto("bbb2222", "2026-10-25T10:00:00Z", "9.0.0"))
    _dejar(paquetes, tmp_path, _manifiesto("aaa1111", "2026-10-24T10:00:00Z", "9.0.0"))
    sincronizar(reg, paquetes, "districash")
    v = next(v for v in reg.versiones("districash", "deteccion-clientes-perdidos") if v["numero"] == "9.0.0")
    assert v["commit"] == "aaa1111"


def test_paquete_de_una_version_vieja_desde_git(tmp_path):
    zip_local, manifiesto = armar_desde_git("districash", "002fa7e", tmp_path)
    versiones = {c["id"]: c["version"] for c in manifiesto["componentes"]}
    assert versiones["deteccion-clientes-perdidos"] == "0.2.1"
    assert manifiesto["commit"] == "002fa7e"
    assert zip_local.exists()


def test_respaldar_historial_guarda_cada_commit_una_vez(reg, tmp_path):
    paquetes = PaquetesLocal(tmp_path / "bucket")
    guardados = respaldar_historial(reg, paquetes, "districash")
    commits = {v["commit"] for v in reg.almacen.listar("versiones", cliente_id="districash")}
    assert set(guardados) == commits
    assert respaldar_historial(reg, paquetes, "districash") == []
    destino = paquetes.descargar("districash", "66ca0fe", tmp_path / "abierto")
    m = json.loads((destino / "exek" / "manifiesto.json").read_text(encoding="utf-8"))
    assert {c["id"]: c["version"] for c in m["componentes"]}["deteccion-clientes-perdidos"] == "0.2.2"
