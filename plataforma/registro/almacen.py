"""Dónde se guardan las filas del registro.

Dos implementaciones con el mismo comportamiento:
- AlmacenBigQuery: el registro real (dataset exekai.exek_registro).
- AlmacenMemoria: para las pruebas automáticas, sin tocar GCP.

BigQuery no impide claves repetidas ni cambios simultáneos, así que estas reglas se
cumplen aquí: insertar falla si la clave ya existe y actualizar o eliminar fallan si
la `revision` no es la que se leyó (alguien cambió el dato mientras tanto).
"""
from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from registro.esquema import TABLAS, Tabla


class ErrorAlmacen(Exception):
    pass


class Duplicado(ErrorAlmacen):
    pass


class NoExiste(ErrorAlmacen):
    pass


class Conflicto(ErrorAlmacen):
    """El dato cambió desde que se leyó."""


def ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _clave(tabla: Tabla, fila: dict) -> tuple:
    return tuple(fila[k] for k in tabla.clave)


def _revisar_fila(tabla: Tabla, fila: dict) -> dict:
    desconocidas = set(fila) - set(tabla.nombres)
    if desconocidas:
        raise ErrorAlmacen(f"{tabla.nombre} no tiene las columnas {sorted(desconocidas)}")
    completa = {}
    for c in tabla.columnas:
        valor = fila.get(c.nombre)
        if c.lista:
            valor = list(valor or [])
        if c.obligatoria and valor in (None, ""):
            raise ErrorAlmacen(f"falta {c.nombre} en {tabla.nombre}")
        completa[c.nombre] = valor
    return completa


class Almacen:
    """Operaciones básicas sobre las tablas del registro."""

    def preparar(self) -> None:
        """Crea las tablas que falten."""

    def listar(self, tabla: str, **filtros) -> list[dict]:
        raise NotImplementedError

    def obtener(self, tabla: str, **clave) -> dict | None:
        filas = self.listar(tabla, **clave)
        return filas[0] if filas else None

    def insertar(self, tabla: str, fila: dict) -> dict:
        raise NotImplementedError

    def actualizar(self, tabla: str, clave: dict, cambios: dict, revision: int) -> dict:
        raise NotImplementedError

    def eliminar(self, tabla: str, clave: dict, revision: int) -> None:
        raise NotImplementedError


class AlmacenMemoria(Almacen):
    def __init__(self):
        self.tablas: dict[str, list[dict]] = {n: [] for n in TABLAS}

    def listar(self, tabla: str, **filtros) -> list[dict]:
        t = TABLAS[tabla]
        filas = [f for f in self.tablas[tabla] if all(f.get(k) == v for k, v in filtros.items())]
        if t.clave:
            filas.sort(key=lambda f: _clave(t, f))
        return copy.deepcopy(filas)

    def insertar(self, tabla: str, fila: dict) -> dict:
        t = TABLAS[tabla]
        fila = _revisar_fila(t, fila)
        if t.clave and any(_clave(t, f) == _clave(t, fila) for f in self.tablas[tabla]):
            raise Duplicado(f"ya existe {dict(zip(t.clave, _clave(t, fila)))} en {tabla}")
        self.tablas[tabla].append(copy.deepcopy(fila))
        return copy.deepcopy(fila)

    def _buscar(self, t: Tabla, clave: dict) -> dict:
        for f in self.tablas[t.nombre]:
            if all(f[k] == clave[k] for k in t.clave):
                return f
        raise NoExiste(f"no existe {clave} en {t.nombre}")

    def actualizar(self, tabla: str, clave: dict, cambios: dict, revision: int) -> dict:
        t = TABLAS[tabla]
        f = self._buscar(t, clave)
        if f["revision"] != revision:
            raise Conflicto(f"{tabla} {clave} cambió (revisión {f['revision']}, se esperaba {revision})")
        nueva = _revisar_fila(t, {**f, **cambios, "revision": revision + 1})
        f.clear()
        f.update(nueva)
        return copy.deepcopy(f)

    def eliminar(self, tabla: str, clave: dict, revision: int) -> None:
        t = TABLAS[tabla]
        f = self._buscar(t, clave)
        if f["revision"] != revision:
            raise Conflicto(f"{tabla} {clave} cambió (revisión {f['revision']}, se esperaba {revision})")
        self.tablas[tabla].remove(f)


class AlmacenBigQuery(Almacen):
    """Registro en un dataset de BigQuery. Escribe con DML (no streaming), para que
    las filas se puedan actualizar de inmediato."""

    def __init__(self, proyecto: str, dataset: str, cliente_bq=None):
        from google.cloud import bigquery

        self.bigquery = bigquery
        self.proyecto = proyecto
        self.dataset = dataset
        self.bq = cliente_bq or bigquery.Client(project=proyecto)

    def _ref(self, tabla: str) -> str:
        return f"`{self.proyecto}.{self.dataset}.{tabla}`"

    def preparar(self) -> None:
        bq = self.bigquery
        for t in TABLAS.values():
            esquema = [
                bq.SchemaField(c.nombre, c.tipo, mode="REPEATED" if c.lista else
                               ("REQUIRED" if c.obligatoria else "NULLABLE"))
                for c in t.columnas
            ]
            tabla = bq.Table(f"{self.proyecto}.{self.dataset}.{t.nombre}", schema=esquema)
            tabla.description = t.descripcion
            self.bq.create_table(tabla, exists_ok=True)

    def _param(self, t: Tabla, nombre: str, valor: Any, alias: str | None = None):
        c = t.columna(nombre)
        if c.lista:
            return self.bigquery.ArrayQueryParameter(alias or nombre, c.tipo, list(valor or []))
        return self.bigquery.ScalarQueryParameter(alias or nombre, c.tipo, valor)

    def _ejecutar(self, sql: str, params: list):
        cfg = self.bigquery.QueryJobConfig(query_parameters=params, labels={"origen": "consola-exek"})
        job = self.bq.query(sql, job_config=cfg)
        filas = list(job.result())
        return job, filas

    def _donde(self, t: Tabla, filtros: dict, prefijo: str = "f_") -> tuple[str, list]:
        partes, params = [], []
        for k, v in filtros.items():
            if v is None:
                partes.append(f"{k} IS NULL")
            else:
                partes.append(f"{k} = @{prefijo}{k}")
                params.append(self._param(t, k, v, prefijo + k))
        return (" AND ".join(partes) or "TRUE"), params

    def listar(self, tabla: str, **filtros) -> list[dict]:
        t = TABLAS[tabla]
        donde, params = self._donde(t, filtros)
        orden = f" ORDER BY {', '.join(t.clave)}" if t.clave else " ORDER BY fecha DESC"
        _, filas = self._ejecutar(f"SELECT * FROM {self._ref(tabla)} WHERE {donde}{orden}", params)
        return [{c.nombre: (list(f[c.nombre] or []) if c.lista else f[c.nombre]) for c in t.columnas} for f in filas]

    def insertar(self, tabla: str, fila: dict) -> dict:
        t = TABLAS[tabla]
        fila = _revisar_fila(t, fila)
        cols = t.nombres
        params = [self._param(t, c, fila[c], "v_" + c) for c in cols]
        sql = f"INSERT INTO {self._ref(tabla)} ({', '.join(cols)}) SELECT {', '.join('@v_' + c for c in cols)}"
        if t.clave:
            donde, p2 = self._donde(t, {k: fila[k] for k in t.clave})
            sql += f" FROM UNNEST([1]) WHERE NOT EXISTS (SELECT 1 FROM {self._ref(tabla)} WHERE {donde})"
            params += p2
        job, _ = self._ejecutar(sql, params)
        if t.clave and not job.num_dml_affected_rows:
            raise Duplicado(f"ya existe {dict(zip(t.clave, _clave(t, fila)))} en {tabla}")
        return fila

    def actualizar(self, tabla: str, clave: dict, cambios: dict, revision: int) -> dict:
        t = TABLAS[tabla]
        actual = self.obtener(tabla, **clave)
        if actual is None:
            raise NoExiste(f"no existe {clave} en {tabla}")
        nueva = _revisar_fila(t, {**actual, **cambios, "revision": revision + 1})
        poner = [c for c in t.nombres if c not in t.clave]
        params = [self._param(t, c, nueva[c], "v_" + c) for c in poner]
        donde, p2 = self._donde(t, clave)
        sql = (f"UPDATE {self._ref(tabla)} SET {', '.join(f'{c} = @v_{c}' for c in poner)} "
               f"WHERE {donde} AND revision = @rev_esperada")
        params += p2 + [self.bigquery.ScalarQueryParameter("rev_esperada", "INT64", revision)]
        job, _ = self._ejecutar(sql, params)
        if not job.num_dml_affected_rows:
            raise Conflicto(f"{tabla} {clave} cambió desde que se leyó")
        return nueva

    def eliminar(self, tabla: str, clave: dict, revision: int) -> None:
        t = TABLAS[tabla]
        donde, params = self._donde(t, clave)
        params.append(self.bigquery.ScalarQueryParameter("rev_esperada", "INT64", revision))
        job, _ = self._ejecutar(f"DELETE FROM {self._ref(tabla)} WHERE {donde} AND revision = @rev_esperada", params)
        if not job.num_dml_affected_rows:
            if self.obtener(tabla, **clave) is None:
                raise NoExiste(f"no existe {clave} en {tabla}")
            raise Conflicto(f"{tabla} {clave} cambió desde que se leyó")
