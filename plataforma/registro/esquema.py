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
    tipo: str  # STRING, INT64, FLOAT64, BOOL, DATE, TIMESTAMP
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
    _c("margen_pct", "FLOAT64"),  # margen sobre el costo para facturar (0.3 = 30 %)
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
    _c("cron", obligatoria=True),  # resumen legible de la frecuencia (lo arma la consola)
    _c("zona_horaria", obligatoria=True),
    _c("activa", "BOOL"),
    _c("destinatarios", lista=True),  # rol:<id> o correo
    _c("canales", lista=True),  # portal (siempre) y correo (si enviar_correo)
    _c("frecuencia"),  # diaria | semanal | mensual | horas
    _c("hora"),  # HH:MM, hora local
    _c("dias", lista=True),  # semanal: lun, mar, mie, jue, vie, sab, dom
    _c("dia_mes", "INT64"),  # mensual: 1 a 31 (si el mes es más corto, el último día)
    _c("cada_horas", "INT64"),  # horas: cada N horas desde la hora indicada
    _c("fecha_inicio", "DATE"),
    _c("fecha_fin", "DATE"),  # vacía = sin fin
    _c("enviar_correo", "BOOL"),
    *AUDITORIA,
), descripcion="Cuándo corre cada agente o artefacto, entre qué fechas y si avisa por correo")

EJECUCIONES = Tabla("ejecuciones", ("ejecucion_id",), (
    _c("ejecucion_id", obligatoria=True),
    _c("cliente_id", obligatoria=True),
    _c("disparador", obligatoria=True),  # programacion | manual | eco
    _c("componente_id"),  # vacío en conversaciones de ECO (pueden usar varios)
    _c("tipo"),  # agente | artefacto | conversacion
    _c("version"),
    _c("componentes", lista=True),  # id@versión de lo que se usó
    _c("programacion_id"),
    _c("ocurrencia", "TIMESTAMP"),  # hora programada que atiende (evita correr dos veces la misma)
    _c("usuario"),  # quién la pidió (ECO o "Ejecutar ahora"); vacío si fue el reloj
    _c("inicio", "TIMESTAMP", obligatoria=True),
    _c("fin", "TIMESTAMP"),
    _c("duracion_ms", "INT64"),
    _c("estado", obligatoria=True),  # en_curso | terminada | error
    _c("resumen"),  # texto corto para listas y correos
    _c("resultado"),  # JSON: texto de la alerta o datos del tablero
    _c("correo_enviado", "BOOL"),
    _c("correo_destinatarios", lista=True),
    _c("correo_error"),
    _c("modelo"),
    _c("tokens_entrada", "INT64"),
    _c("tokens_salida", "INT64"),
    _c("tokens_cache_lectura", "INT64"),
    _c("tokens_cache_escritura", "INT64"),
    _c("bytes_facturados", "INT64"),
    _c("costo_claude_usd", "FLOAT64"),
    _c("costo_bigquery_usd", "FLOAT64"),
    _c("costo_total_usd", "FLOAT64"),
    _c("error"),
    *AUDITORIA,
), descripcion="Cada corrida de un agente, artefacto o conversación de ECO: inicio, fin, resultado y costo")

TABLAS = {t.nombre: t for t in (CLIENTES, ETIQUETAS, ROLES, USUARIOS, COMPONENTES, VERSIONES, HISTORIAL, PROGRAMACIONES,
                                 EJECUCIONES)}
