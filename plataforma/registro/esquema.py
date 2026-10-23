"""Tablas del registro de la Consola Exek (dataset exekai.exek_registro).

Modelo de datos v4 (docs/definiciones.md, sección 4). Lo que hace cada componente
vive en Git; aquí vive quién lo usa, con qué etiquetas y qué versión está publicada.

Las tablas que se editan llevan columnas de auditoría y una `revision` que sube con
cada cambio: así la consola detecta si alguien cambió el dato mientras otro lo editaba.
Las versiones y el historial solo se agregan, nunca se modifican.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Columna:
    nombre: str
    tipo: str  # STRING, INT64, BOOL, TIMESTAMP
    lista: bool = False
    obligatoria: bool = False


@dataclass(frozen=True)
class Tabla:
    nombre: str
    clave: tuple[str, ...]
    columnas: tuple[Columna, ...]
    editable: bool = True
    descripcion: str = ""

    def columna(self, nombre: str) -> Columna:
        for c in self.columnas:
            if c.nombre == nombre:
                return c
        raise KeyError(f"{self.nombre} no tiene la columna {nombre}")

    @property
    def nombres(self) -> list[str]:
        return [c.nombre for c in self.columnas]


def _c(nombre, tipo="STRING", lista=False, obligatoria=False) -> Columna:
    return Columna(nombre, tipo, lista, obligatoria)


AUDITORIA = (
    _c("creado", "TIMESTAMP", obligatoria=True),
    _c("creado_por", obligatoria=True),
    _c("actualizado", "TIMESTAMP", obligatoria=True),
    _c("actualizado_por", obligatoria=True),
    _c("revision", "INT64", obligatoria=True),
)

CLIENTES = Tabla("clientes", ("cliente_id",), (
    _c("cliente_id", obligatoria=True),
    _c("nombre", obligatoria=True),
    _c("dominios", lista=True),
    _c("proyecto_datos", obligatoria=True),
    _c("dataset", obligatoria=True),
    _c("cuenta_eco", obligatoria=True),
    _c("acceso_verificado", "BOOL"),
    _c("estado", obligatoria=True),  # activo | inactivo
    *AUDITORIA,
), descripcion="Clientes de Exek y dónde están sus datos")

ETIQUETAS = Tabla("etiquetas", ("cliente_id", "etiqueta_id"), (
    _c("cliente_id", obligatoria=True),
    _c("etiqueta_id", obligatoria=True),
    _c("nombre", obligatoria=True),
    _c("color"),
    *AUDITORIA,
), descripcion="Etiquetas de cada cliente: organizan el almacén y dan los permisos")

ROLES = Tabla("roles", ("cliente_id", "rol_id"), (
    _c("cliente_id", obligatoria=True),
    _c("rol_id", obligatoria=True),
    _c("nombre", obligatoria=True),
    _c("descripcion"),
    _c("etiquetas", lista=True),
    *AUDITORIA,
), descripcion="Roles de cada cliente y las etiquetas que pueden usar")

USUARIOS = Tabla("usuarios", ("correo",), (
    _c("correo", obligatoria=True),
    _c("cliente_id", obligatoria=True),
    _c("nombre"),
    _c("rol_id", obligatoria=True),
    _c("estado", obligatoria=True),  # activo | inactivo
    *AUDITORIA,
), descripcion="Usuarios de los clientes (solo registro hasta la fase 6)")

COMPONENTES = Tabla("componentes", ("cliente_id", "componente_id"), (
    _c("cliente_id", obligatoria=True),
    _c("componente_id", obligatoria=True),
    _c("tipo", obligatoria=True),  # skill | agente | artefacto | plugin
    _c("nombre", obligatoria=True),
    _c("etiquetas", lista=True),
    _c("visible_portal", "BOOL"),
    _c("version_produccion"),
    _c("estado", obligatoria=True),  # activo | retirado
    *AUDITORIA,
), descripcion="Componentes del almacén de cada cliente y su versión publicada")

VERSIONES = Tabla("versiones", ("cliente_id", "componente_id", "numero"), (
    _c("cliente_id", obligatoria=True),
    _c("componente_id", obligatoria=True),
    _c("numero", obligatoria=True),
    _c("commit", obligatoria=True),
    _c("notas"),
    _c("autor"),
    _c("paquete_uri"),
    _c("registrada", "TIMESTAMP", obligatoria=True),
    _c("registrada_por", obligatoria=True),
), editable=False, descripcion="Versiones de cada componente que llegaron a main")

HISTORIAL = Tabla("historial", (), (
    _c("fecha", "TIMESTAMP", obligatoria=True),
    _c("cliente_id"),
    _c("quien", obligatoria=True),
    _c("tipo", obligatoria=True),  # cliente | etiqueta | rol | usuario | componente | version
    _c("accion", obligatoria=True),  # crear | actualizar | eliminar | registrar | publicar | retirar
    _c("objeto_id"),
    _c("detalle", obligatoria=True),
    _c("antes"),  # JSON
    _c("despues"),  # JSON
), editable=False, descripcion="Quién cambió qué y cuándo")

PROGRAMACIONES = Tabla("programaciones", ("cliente_id", "programacion_id"), (
    _c("cliente_id", obligatoria=True),
    _c("programacion_id", obligatoria=True),
    _c("componente_id", obligatoria=True),
    _c("cron", obligatoria=True),
    _c("zona_horaria", obligatoria=True),
    _c("activa", "BOOL"),
    _c("destinatarios", lista=True),  # rol:<id> o correo
    _c("canales", lista=True),  # correo | portal
    *AUDITORIA,
), descripcion="Cuándo corre cada agente o artefacto (se usa en la fase 4)")

TABLAS = {t.nombre: t for t in (CLIENTES, ETIQUETAS, ROLES, USUARIOS, COMPONENTES, VERSIONES, HISTORIAL, PROGRAMACIONES)}
