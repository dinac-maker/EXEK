"""Pruebas del registro de la Consola Exek.

Uso (desde la carpeta plataforma/):
    python -m pytest registro                                   en memoria, sin GCP
    REGISTRO_PRUEBAS_DATASET=exek_registro_pruebas python -m pytest registro
                                                                contra BigQuery (dataset de pruebas)
"""
from __future__ import annotations

import os
import uuid

import pytest

from registro.almacen import AlmacenBigQuery, AlmacenMemoria, Conflicto, Duplicado
from registro.carga_inicial import cargar
from registro.servicio import ErrorRegistro, Registro

EXEK = "dina.silva@exek.co"


@pytest.fixture
def reg():
    dataset = os.environ.get("REGISTRO_PRUEBAS_DATASET")
    if dataset:
        # Un juego de tablas propio por prueba (prefijo al azar), para no mezclar datos.
        from registro import esquema
        sufijo = uuid.uuid4().hex[:6]
        originales = {n: t for n, t in esquema.TABLAS.items()}
        almacen = AlmacenBigQuery(os.environ.get("REGISTRO_PRUEBAS_PROYECTO", "exekai"), dataset)
        almacen._ref = lambda tabla: f"`{almacen.proyecto}.{almacen.dataset}.{tabla}_{sufijo}`"
        _preparar_con_sufijo(almacen, originales, sufijo)
        return Registro(almacen)
    return Registro(AlmacenMemoria())


def _preparar_con_sufijo(almacen, tablas, sufijo):
    bq = almacen.bigquery
    import datetime as dt
    for t in tablas.values():
        esquema = [bq.SchemaField(c.nombre, c.tipo, mode="REPEATED" if c.lista else ("REQUIRED" if c.obligatoria else "NULLABLE"))
                   for c in t.columnas]
        tabla = bq.Table(f"{almacen.proyecto}.{almacen.dataset}.{t.nombre}_{sufijo}", schema=esquema)
        tabla.expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=6)
        almacen.bq.create_table(tabla, exists_ok=True)


@pytest.fixture
def districash(reg):
    cargar(reg)
    return reg


# ---- almacén --------------------------------------------------------------------

def test_almacen_no_duplica_ni_pisa_cambios():
    a = AlmacenMemoria()
    fila = {"cliente_id": "x", "etiqueta_id": "ventas", "nombre": "Ventas", "color": None, "creado": 1,
            "creado_por": EXEK, "actualizado": 1, "actualizado_por": EXEK, "revision": 1}
    a.insertar("etiquetas", fila)
    with pytest.raises(Duplicado):
        a.insertar("etiquetas", fila)
    a.actualizar("etiquetas", {"cliente_id": "x", "etiqueta_id": "ventas"}, {"nombre": "Venta"}, 1)
    with pytest.raises(Conflicto):  # otra persona tenía la revisión 1
        a.actualizar("etiquetas", {"cliente_id": "x", "etiqueta_id": "ventas"}, {"nombre": "V"}, 1)


# ---- clientes -------------------------------------------------------------------

def test_alta_de_cliente_valida_los_datos(reg):
    c = reg.crear_cliente(EXEK, "Ferretería Andina", ["FerreAndina.co"], "exek-ferreandina", "ventas")
    assert c["cliente_id"] == "ferreteria-andina"
    assert c["dominios"] == ["ferreandina.co"]
    assert c["cuenta_eco"] == "eco-ferreteria-andina@exekai.iam.gserviceaccount.com"
    assert c["acceso_verificado"] is False
    with pytest.raises(ErrorRegistro, match="Ya existe"):
        reg.crear_cliente(EXEK, "Ferretería Andina", ["ferreandina.co"], "exek-ferreandina", "ventas")
    with pytest.raises(ErrorRegistro, match="dominios"):
        reg.crear_cliente(EXEK, "Otro", ["no es un dominio"], "exek-otro", "ventas")
    with pytest.raises(ErrorRegistro, match="proyecto"):
        reg.crear_cliente(EXEK, "Otro", ["otro.com"], "X", "ventas")
    with pytest.raises(ErrorRegistro, match="dataset"):
        reg.crear_cliente(EXEK, "Otro", ["otro.com"], "exek-otro", "ventas-2026")
    largo = reg.crear_cliente(EXEK, "Distribuidora Nacional de Ferreterías del Caribe", ["dnfc.co"], "exek-dnfc", "ventas")
    assert len(largo["cuenta_eco"].split("@")[0]) <= 30  # límite de GCP para cuentas de servicio


def test_cambiar_proyecto_obliga_a_verificar_de_nuevo(reg):
    c = reg.crear_cliente(EXEK, "Andina", ["andina.co"], "exek-andina", "ventas")
    c = reg.actualizar_cliente(EXEK, "andina", c["revision"], acceso_verificado=True)
    c = reg.actualizar_cliente(EXEK, "andina", c["revision"], dataset="ventas_v2")
    assert c["acceso_verificado"] is False
    with pytest.raises(ErrorRegistro, match="Alguien cambió"):
        reg.actualizar_cliente(EXEK, "andina", c["revision"] - 1, nombre="Andina SAS")


# ---- etiquetas, roles y usuarios ------------------------------------------------

def test_etiqueta_en_uso_no_se_elimina(districash):
    ventas = next(e for e in districash.etiquetas("districash") if e["etiqueta_id"] == "ventas")
    with pytest.raises(ErrorRegistro, match="en uso"):
        districash.eliminar_etiqueta(EXEK, "districash", "ventas", ventas["revision"])
    nueva = districash.crear_etiqueta(EXEK, "districash", "Logística")
    districash.eliminar_etiqueta(EXEK, "districash", "logistica", nueva["revision"])
    assert "logistica" not in {e["etiqueta_id"] for e in districash.etiquetas("districash")}


def test_renombrar_etiqueta_conserva_permisos(districash):
    ventas = next(e for e in districash.etiquetas("districash") if e["etiqueta_id"] == "ventas")
    districash.renombrar_etiqueta(EXEK, "districash", "ventas", "Ventas nacionales", ventas["revision"])
    assert len(districash.permitidos_para_rol("districash", "comercial")) == 3


def test_rol_solo_acepta_etiquetas_del_cliente(districash):
    with pytest.raises(ErrorRegistro, match="no existen"):
        districash.crear_rol(EXEK, "districash", "Logística", ["transporte"])


def test_usuario_debe_ser_del_dominio_del_cliente(districash):
    u = districash.crear_usuario(EXEK, "districash", "Ventas.Norte@Exek.co", "comercial", "Coordinador")
    assert u["correo"] == "ventas.norte@exek.co"
    with pytest.raises(ErrorRegistro, match="exek.co"):
        districash.crear_usuario(EXEK, "districash", "alguien@gmail.com", "comercial")
    with pytest.raises(ErrorRegistro, match="ya está registrado"):
        districash.crear_usuario(EXEK, "districash", "ventas.norte@exek.co", "gerencia")
    with pytest.raises(ErrorRegistro, match="rol"):
        districash.crear_usuario(EXEK, "districash", "otro@exek.co", "no-existe")


# ---- permisos por rol (lo que verá ECO) -----------------------------------------

def test_permisos_de_districash_segun_definiciones(districash):
    ve = lambda rol: sorted(c["componente_id"] for c in districash.permitidos_para_rol("districash", rol))
    assert ve("gerencia") == ["deteccion-clientes-perdidos", "indicadores-ventas",
                              "monitor-clientes-perdidos", "tablero-control-gerencia"]
    assert ve("comercial") == ["deteccion-clientes-perdidos", "indicadores-ventas", "monitor-clientes-perdidos"]
    assert ve("compras") == []


def test_usuario_inactivo_no_ve_nada(districash):
    u = districash.crear_usuario(EXEK, "districash", "gerente@exek.co", "gerencia")
    assert len(districash.permitidos_para_usuario("gerente@exek.co")[1]) == 4
    districash.actualizar_usuario(EXEK, "gerente@exek.co", u["revision"], estado="inactivo")
    assert districash.permitidos_para_usuario("gerente@exek.co")[1] == []
    assert districash.permitidos_para_usuario("nadie@exek.co") == (None, [])


# ---- versiones, publicar, volver atrás y retirar --------------------------------

def test_versiones_y_estados(districash):
    vs = districash.versiones("districash", "deteccion-clientes-perdidos")
    assert [(v["numero"], v["estado"]) for v in vs] == [
        ("0.2.2", "en_produccion"), ("0.2.1", "anterior"), ("0.2.0", "anterior"), ("0.1.0", "anterior")]
    assert districash.registrar_version("districash", "deteccion-clientes-perdidos", "skill",
                                        "Detección de clientes perdidos", "0.2.2", "66ca0fe") is None  # ya estaba
    districash.registrar_version("districash", "deteccion-clientes-perdidos", "skill",
                                 "Detección de clientes perdidos", "0.3.0", "abc1234", "Nueva ventana")
    assert districash.version_en_prueba("districash", "deteccion-clientes-perdidos") == "0.3.0"


def test_publicar_volver_atras_y_retirar(districash):
    cid, comp = "districash", "deteccion-clientes-perdidos"
    districash.registrar_version(cid, comp, "skill", "Detección de clientes perdidos", "0.3.0", "abc1234")
    c = districash.componente(cid, comp)
    c = districash.publicar(EXEK, cid, comp, "0.3.0", c["revision"])
    assert c["version_produccion"] == "0.3.0"
    with pytest.raises(ErrorRegistro, match="ya está en producción"):
        districash.publicar(EXEK, cid, comp, "0.3.0", c["revision"])
    c = districash.publicar(EXEK, cid, comp, "0.2.1", c["revision"])  # volver atrás
    estados = {v["numero"]: v["estado"] for v in districash.versiones(cid, comp)}
    # Lo más nuevo que la versión publicada queda "en prueba": se puede volver a publicar.
    assert estados == {"0.3.0": "en_prueba", "0.2.2": "en_prueba", "0.2.1": "en_produccion",
                       "0.2.0": "anterior", "0.1.0": "anterior"}
    assert districash.version_en_prueba(cid, comp) == "0.3.0"
    assert "volvió a la versión 0.2.1" in districash.historial(cid)[0]["detalle"]
    c = districash.retirar(EXEK, cid, comp, c["revision"])
    assert comp not in {x["componente_id"] for x in districash.publicados(cid)}
    assert comp not in {x["componente_id"] for x in districash.permitidos_para_rol(cid, "comercial")}
    with pytest.raises(ErrorRegistro, match="no está registrada"):
        districash.publicar(EXEK, cid, comp, "9.9.9", c["revision"])


def test_todo_queda_en_el_historial(districash):
    h = districash.historial("districash")
    assert all(x["quien"] and x["detalle"] and x["fecha"] for x in h)
    tipos = {x["tipo"] for x in h}
    assert {"cliente", "etiqueta", "rol", "componente", "version"} <= tipos


def test_la_carga_inicial_se_puede_repetir(districash):
    antes = len(districash.historial("districash"))
    cargar(districash)
    assert len(districash.historial("districash")) == antes


def test_almacen_completo_coincide_con_las_consultas_por_componente(districash):
    districash.registrar_version("districash", "deteccion-clientes-perdidos", "skill",
                                 "Detección de clientes perdidos", "0.3.0", "abc1234")
    completo = {c["componente_id"]: c for c in districash.almacen_completo("districash")}
    for cid, c in completo.items():
        assert c["en_prueba"] == districash.version_en_prueba("districash", cid)
        assert [v["estado"] for v in c["versiones"]] == [v["estado"] for v in districash.versiones("districash", cid)]
    assert completo["deteccion-clientes-perdidos"]["en_prueba"] == "0.3.0"


def test_buscar_en_todo_el_almacen_dice_que_cliente_lo_tiene(districash):
    districash.crear_cliente(EXEK, "Ferretería Andina", ["ferreandina.co"], "exek-ferreandina", "ventas")
    districash.registrar_version("ferreteria-andina", "deteccion-clientes-perdidos", "skill",
                                 "Detección de clientes perdidos", "0.1.0", "fff0001")
    todo = districash.almacen_global()
    perdidos = [c for c in todo if c["componente_id"] == "deteccion-clientes-perdidos"]
    assert sorted(c["cliente_nombre"] for c in perdidos) == ["Districash", "Ferretería Andina"]
    andina = next(c for c in perdidos if c["cliente_id"] == "ferreteria-andina")
    assert andina["version_produccion"] is None and andina["en_prueba"] == "0.1.0"
    tablero = next(c for c in todo if c["componente_id"] == "tablero-control-gerencia")
    assert tablero["etiquetas_nombres"] == ["Gerencia"] and tablero["cliente_nombre"] == "Districash"
