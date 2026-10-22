"""Consulta segura de BigQuery para ECO.

Dos herramientas, servidas a Claude como servidor MCP dentro del mismo proceso:

- ejecutar_skill: corre el consulta.sql de un skill con los parámetros de su ficha.
  Claude no puede cambiar esos parámetros (por ejemplo, los 60 días de cliente perdido).
- consulta_libre: un SELECT escrito por Claude. Antes de correrlo se hace una prueba
  sin leer datos (dry run) y se rechaza si no es un SELECT o si toca tablas que no
  estén declaradas en fuentes/ del cliente.

Todas las consultas llevan el límite de bytes del manifiesto y etiquetas del cliente.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import decimal
import json
import re
import time
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from eco.configuracion import FILAS_MAXIMAS, FILAS_POR_DEFECTO, Cliente
from eco.paquete import Paquete
from comun import parametros_en_sql  # herramientas/comun.py (ruta agregada en eco.paquete)

NOMBRE_SERVIDOR = "bigquery"
HERRAMIENTAS = [f"mcp__{NOMBRE_SERVIDOR}__ejecutar_skill", f"mcp__{NOMBRE_SERVIDOR}__consulta_libre"]

PROHIBIDO_EN_SQL = re.compile(r"\bINFORMATION_SCHEMA\b", re.IGNORECASE)


class ConsultaRechazada(Exception):
    """La consulta no cumple las reglas de ECO; el mensaje se le muestra a Claude."""


def _etiqueta(valor: str) -> str:
    """Valor válido para una etiqueta de BigQuery (minúsculas, números, - y _)."""
    return re.sub(r"[^a-z0-9_-]", "-", valor.lower())[:63]


def _a_json(valor: Any) -> Any:
    if isinstance(valor, (dt.date, dt.datetime, dt.time)):
        return valor.isoformat()
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    if isinstance(valor, bytes):
        return valor.decode("utf-8", "replace")
    return valor


def _tipo_parametro(valor: Any) -> str:
    if isinstance(valor, bool):
        return "BOOL"
    if isinstance(valor, int):
        return "INT64"
    if isinstance(valor, float):
        return "FLOAT64"
    return "STRING"


class ConsultasBigQuery:
    """Ejecuta las consultas de una conversación y anota cada una en `self.consultas`."""

    def __init__(self, cliente: Cliente, paquete: Paquete):
        self.cliente = cliente
        self.paquete = paquete
        self.consultas: list[dict] = []
        self._bq = None

    @property
    def bq(self):
        if self._bq is None:
            from google.cloud import bigquery

            self._bq = bigquery.Client(project=self.cliente.proyecto_consultas)
        return self._bq

    def _config(self, componente: str, parametros: list | None = None, dry_run: bool = False):
        from google.cloud import bigquery

        cfg = bigquery.QueryJobConfig(
            dry_run=dry_run,
            use_query_cache=not dry_run,
            query_parameters=parametros or [],
            labels={
                "cliente": _etiqueta(self.cliente.cliente_id),
                "origen": "eco",
                "componente": _etiqueta(componente),
            },
        )
        if not dry_run:
            cfg.maximum_bytes_billed = self.cliente.limite_bytes
        return cfg

    def _revisar_tablas(self, job) -> list[str]:
        usadas = sorted(f"{t.project}.{t.dataset_id}.{t.table_id}" for t in (job.referenced_tables or []))
        no_declaradas = [t for t in usadas if t not in self.paquete.tablas_permitidas]
        if no_declaradas:
            raise ConsultaRechazada(
                "La consulta usa tablas que no están declaradas para este cliente: "
                + ", ".join(no_declaradas)
                + ". Solo puedes usar: " + ", ".join(sorted(self.paquete.tablas_permitidas))
            )
        return usadas

    def _ejecutar(self, sql: str, componente: str, parametros: list, max_filas: int) -> dict:
        """Prueba la consulta sin leer datos, revisa las reglas y la ejecuta."""
        inicio = time.monotonic()
        prueba = self.bq.query(sql, job_config=self._config(componente, parametros, dry_run=True))
        if (prueba.statement_type or "").upper() != "SELECT":
            raise ConsultaRechazada(f"Solo se permiten consultas SELECT (esta es {prueba.statement_type}).")
        tablas = self._revisar_tablas(prueba)
        if prueba.total_bytes_processed and prueba.total_bytes_processed > self.cliente.limite_bytes:
            raise ConsultaRechazada(
                f"La consulta leería {prueba.total_bytes_processed / 1e9:.2f} GB, más que el límite "
                f"del cliente ({self.cliente.limite_bytes / 1e9:.2f} GB). Filtra por fechas o columnas."
            )

        job = self.bq.query(sql, job_config=self._config(componente, parametros))
        filas_iter = job.result(max_results=max_filas)
        filas = [{k: _a_json(v) for k, v in dict(f).items()} for f in filas_iter]
        total = filas_iter.total_rows if filas_iter.total_rows is not None else len(filas)
        registro = {
            "componente": componente,
            "job_id": job.job_id,
            "bytes_procesados": job.total_bytes_processed,
            "bytes_facturados": job.total_bytes_billed,
            "tablas": tablas,
            "filas_total": total,
            "filas_devueltas": len(filas),
            "segundos": round(time.monotonic() - inicio, 2),
        }
        self.consultas.append(registro)
        return {
            "filas_total": total,
            "filas_devueltas": len(filas),
            "aviso": None if total <= len(filas) else
                f"Se devolvieron las primeras {len(filas)} de {total} filas, en el orden de la consulta.",
            "filas": filas,
        }

    def _anotar_rechazo(self, componente: str, motivo: str) -> None:
        self.consultas.append({"componente": componente, "rechazada": True, "motivo": motivo})

    # ---- Herramientas -------------------------------------------------------------

    def ejecutar_skill(self, skill_id: str, max_filas: int) -> dict:
        skill = self.paquete.skills.get(skill_id)
        if skill is None:
            raise ConsultaRechazada(
                f"No existe un skill con consulta llamado '{skill_id}'. Disponibles: "
                + ", ".join(sorted(self.paquete.skills))
            )
        from google.cloud import bigquery

        usados = parametros_en_sql(skill.sql)
        parametros = [
            bigquery.ScalarQueryParameter(nombre, _tipo_parametro(valor), valor)
            for nombre, valor in skill.parametros.items()
            if nombre in usados
        ]
        resultado = self._ejecutar(skill.sql, skill.id, parametros, max_filas)
        self.consultas[-1]["skill_version"] = skill.version
        self.consultas[-1]["parametros"] = {p.name: p.value for p in parametros}
        return {"skill": skill.id, "version": skill.version,
                "parametros": {p.name: p.value for p in parametros}, **resultado}

    def consulta_libre(self, sql: str, max_filas: int) -> dict:
        if PROHIBIDO_EN_SQL.search(sql):
            raise ConsultaRechazada("No se permiten consultas a INFORMATION_SCHEMA.")
        resultado = self._ejecutar(sql, "consulta-libre", [], max_filas)
        self.consultas[-1]["sql"] = sql
        return resultado

    def servidor(self):
        """Servidor MCP en proceso con las dos herramientas."""

        def _filas(args: dict) -> int:
            try:
                n = int(args.get("max_filas") or FILAS_POR_DEFECTO)
            except (TypeError, ValueError):
                n = FILAS_POR_DEFECTO
            return max(1, min(n, FILAS_MAXIMAS))

        async def _responder(componente: str, funcion, *argumentos) -> dict:
            try:
                datos = await asyncio.to_thread(funcion, *argumentos)
            except ConsultaRechazada as e:
                self._anotar_rechazo(componente, str(e))
                return {"content": [{"type": "text", "text": f"Consulta rechazada: {e}"}], "is_error": True}
            except Exception as e:  # noqa: BLE001 - el error de BigQuery se le explica a Claude
                self._anotar_rechazo(componente, f"error de BigQuery: {e}")
                return {"content": [{"type": "text", "text": f"Error de BigQuery: {e}"}], "is_error": True}
            return {"content": [{"type": "text", "text": json.dumps(datos, ensure_ascii=False, default=str)}]}

        skills_disponibles = ", ".join(sorted(self.paquete.skills)) or "ninguno"
        tablas = ", ".join(sorted(self.paquete.tablas_permitidas)) or "ninguna"

        @tool(
            "ejecutar_skill",
            "Ejecuta la consulta SQL oficial de un skill del cliente con los parámetros acordados en su "
            "ficha (no se pueden cambiar). Úsala siempre que un skill tenga consulta. Devuelve filas_total "
            f"(total de filas del resultado) y hasta max_filas filas. Skills con consulta: {skills_disponibles}.",
            {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "Id del skill, por ejemplo deteccion-clientes-perdidos"},
                    "max_filas": {"type": "integer", "minimum": 1, "maximum": FILAS_MAXIMAS,
                                  "description": f"Filas a devolver (por defecto {FILAS_POR_DEFECTO})"},
                },
                "required": ["skill_id"],
                "additionalProperties": False,
            },
        )
        async def ejecutar_skill(args: dict) -> dict:
            return await _responder(args.get("skill_id", ""), self.ejecutar_skill, args.get("skill_id", ""), _filas(args))

        @tool(
            "consulta_libre",
            "Ejecuta una consulta SELECT de solo lectura en BigQuery (GoogleSQL) para preguntas que los skills "
            f"no cubren. Solo puede usar estas tablas, escritas con comillas invertidas: {tablas}. "
            "Prefiere agregar en SQL (SUM, COUNT, GROUP BY) en lugar de traer muchas filas. "
            "Las definiciones de negocio de los skills (por ejemplo, cliente perdido) no se recalculan aquí.",
            {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Consulta SELECT completa"},
                    "max_filas": {"type": "integer", "minimum": 1, "maximum": FILAS_MAXIMAS,
                                  "description": f"Filas a devolver (por defecto {FILAS_POR_DEFECTO})"},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        )
        async def consulta_libre(args: dict) -> dict:
            return await _responder("consulta-libre", self.consulta_libre, args.get("sql", ""), _filas(args))

        return create_sdk_mcp_server(NOMBRE_SERVIDOR, tools=[ejecutar_skill, consulta_libre])
