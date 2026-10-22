#!/usr/bin/env python3
"""Valida el almacén de componentes de un cliente.

Uso:
    python herramientas/validar.py clientes/<cliente> [--bigquery] [--base <ref git>]

Revisa:
  - manifiesto del cliente, fuentes y fichas contra los esquemas de esquemas/
  - que el id de cada componente sea igual a su carpeta y el tipo a la carpeta del tipo
  - que existan los archivos declarados en la ficha
  - encabezados de SKILL.md y agente.md en formato Anthropic
  - referencias: skills usadas, fuentes, indicadores de los tableros, casos de prueba
  - que los SQL solo usen tablas declaradas en fuentes y parámetros declarados en la ficha
  - con --base: que cada componente modificado haya subido su versión
  - con --bigquery: los SQL en modo de prueba de BigQuery (no leen datos)

Termina con código 1 si hay errores.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import (  # noqa: E402
    RAIZ, componentes, leer_esquema, leer_frontmatter, leer_yaml,
    parametros_en_sql, tablas_en_sql,
)

MODELOS_SUBAGENTE = {"sonnet", "opus", "haiku", "inherit"}
PATRON_NOMBRE_SKILL = re.compile(r"^[a-z0-9-]{1,64}$")


class Informe:
    def __init__(self):
        self.errores: list[str] = []
        self.avisos: list[str] = []

    def error(self, donde: str, msg: str):
        self.errores.append(f"{donde}: {msg}")

    def aviso(self, donde: str, msg: str):
        self.avisos.append(f"{donde}: {msg}")


def validar_esquema(datos, esquema: dict, donde: str, inf: Informe):
    for e in sorted(Draft202012Validator(esquema).iter_errors(datos), key=lambda e: list(e.path)):
        campo = ".".join(str(p) for p in e.path) or "(raíz)"
        inf.error(donde, f"campo '{campo}': {e.message}")


def rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(RAIZ))
    except ValueError:
        return str(p)


def validar_cliente(dir_cliente: Path, usar_bigquery: bool, base: str | None) -> Informe:
    inf = Informe()
    dir_cliente = dir_cliente.resolve()

    # 1. Manifiesto
    manifiesto_ruta = dir_cliente / "exek.yaml"
    manifiesto = {}
    if not manifiesto_ruta.exists():
        inf.error(rel(dir_cliente), "falta exek.yaml")
    else:
        manifiesto = leer_yaml(manifiesto_ruta) or {}
        validar_esquema(manifiesto, leer_esquema("cliente.schema.json"), rel(manifiesto_ruta), inf)
        if manifiesto.get("cliente_id") != dir_cliente.name:
            inf.error(rel(manifiesto_ruta), f"cliente_id '{manifiesto.get('cliente_id')}' debe ser igual a la carpeta '{dir_cliente.name}'")

    # 2. Fuentes
    fuentes: dict[str, dict] = {}
    esquema_fuente = leer_esquema("fuente.schema.json")
    for ruta in sorted((dir_cliente / "fuentes").glob("*.yaml")):
        datos = leer_yaml(ruta) or {}
        validar_esquema(datos, esquema_fuente, rel(ruta), inf)
        if datos.get("id") != ruta.stem:
            inf.error(rel(ruta), f"id '{datos.get('id')}' debe ser igual al nombre del archivo '{ruta.stem}'")
        fuentes[datos.get("id", ruta.stem)] = datos
    tablas_declaradas = {f.get("ubicacion"): fid for fid, f in fuentes.items()}

    # 3. Componentes
    esquema_comp = leer_esquema("componente.schema.json")
    fichas: dict[str, dict] = {}
    carpetas: dict[str, Path] = {}
    for tipo, carpeta in componentes(dir_cliente):
        ficha_ruta = carpeta / "componente.yaml"
        donde = rel(carpeta)
        if not ficha_ruta.exists():
            inf.error(donde, "falta componente.yaml")
            continue
        ficha = leer_yaml(ficha_ruta) or {}
        validar_esquema(ficha, esquema_comp, rel(ficha_ruta), inf)
        cid = ficha.get("id")
        if cid != carpeta.name:
            inf.error(donde, f"id '{cid}' debe ser igual a la carpeta '{carpeta.name}'")
        if ficha.get("tipo") != tipo:
            inf.error(donde, f"tipo '{ficha.get('tipo')}' no corresponde a la carpeta (se esperaba '{tipo}')")
        if cid in fichas:
            inf.error(donde, f"id '{cid}' repetido en el almacén")
        fichas[cid] = ficha
        carpetas[cid] = carpeta

        for clave, archivo in (ficha.get("archivos") or {}).items():
            if not (carpeta / archivo).exists():
                inf.error(donde, f"archivos.{clave} apunta a '{archivo}', que no existe")

        for fid in ficha.get("fuentes") or []:
            if fid not in fuentes:
                inf.error(donde, f"usa la fuente '{fid}', que no existe en fuentes/")

        if tipo == "skill":
            validar_skill(carpeta, ficha, tablas_declaradas, inf)
        elif tipo == "agente":
            validar_agente(carpeta, ficha, inf)
        elif tipo == "plugin":
            if ficha.get("destino") and ficha["destino"] not in fuentes:
                inf.error(donde, f"destino '{ficha['destino']}' no existe en fuentes/")

    # 4. Referencias entre componentes
    skills = {cid for cid, f in fichas.items() if f.get("tipo") == "skill"}
    for cid, ficha in fichas.items():
        for s in ficha.get("usa_skills") or []:
            if s not in skills:
                inf.error(rel(carpetas[cid]), f"usa la skill '{s}', que no existe")
            if s == cid:
                inf.error(rel(carpetas[cid]), "una skill no puede usarse a sí misma")
        if ficha.get("tipo") == "artefacto" and ficha.get("subtipo") == "tablero":
            validar_tablero(carpetas[cid], ficha, fichas, inf)

    # 5. Casos de prueba
    casos_ruta = dir_cliente / "pruebas" / "casos.yaml"
    if casos_ruta.exists():
        casos = (leer_yaml(casos_ruta) or {}).get("casos") or []
        if not casos:
            inf.aviso(rel(casos_ruta), "no hay casos de prueba")
        for i, caso in enumerate(casos, 1):
            if not caso.get("pregunta"):
                inf.error(rel(casos_ruta), f"caso {i} sin pregunta")
            for c in caso.get("debe_usar") or []:
                if c not in fichas:
                    inf.error(rel(casos_ruta), f"caso {i} espera usar '{c}', que no existe")
    else:
        inf.aviso(rel(dir_cliente), "no hay pruebas/casos.yaml")

    # 6. Versiones
    if base:
        validar_versiones(dir_cliente, carpetas, fichas, base, inf)

    # 7. BigQuery
    if usar_bigquery:
        validar_bigquery(manifiesto, carpetas, fichas, inf)

    return inf


def validar_skill(carpeta: Path, ficha: dict, tablas_declaradas: dict, inf: Informe):
    donde = rel(carpeta)
    archivos = ficha.get("archivos") or {}
    instr = carpeta / archivos.get("instrucciones", "SKILL.md")
    if instr.name != "SKILL.md":
        inf.error(donde, "las instrucciones de una skill deben llamarse SKILL.md")
    if instr.exists():
        fm, cuerpo = leer_frontmatter(instr)
        if fm is None:
            inf.error(rel(instr), "falta el encabezado --- con name y description")
        else:
            nombre = fm.get("name", "")
            if nombre != ficha.get("id"):
                inf.error(rel(instr), f"name '{nombre}' debe ser igual al id '{ficha.get('id')}'")
            if not PATRON_NOMBRE_SKILL.match(str(nombre)):
                inf.error(rel(instr), "name solo admite minúsculas, números y guiones (máximo 64)")
            desc = str(fm.get("description", "")).strip()
            if not desc or desc.startswith("["):
                inf.error(rel(instr), "falta description (es lo que Claude lee para decidir si usa la skill)")
            elif len(desc) > 1024:
                inf.error(rel(instr), f"description tiene {len(desc)} caracteres; máximo 1024")
        if len(cuerpo.strip()) < 50:
            inf.aviso(rel(instr), "las instrucciones son muy cortas")

    consulta = archivos.get("consulta")
    if consulta and (carpeta / consulta).exists():
        sql = (carpeta / consulta).read_text(encoding="utf-8")
        fuentes_ficha = set(ficha.get("fuentes") or [])
        for tabla in tablas_en_sql(sql):
            fid = tablas_declaradas.get(tabla)
            if fid is None:
                inf.error(rel(carpeta / consulta), f"usa la tabla {tabla}, que no está declarada en fuentes/")
            elif fid not in fuentes_ficha:
                inf.error(rel(carpeta / consulta), f"usa la fuente '{fid}', pero no está en 'fuentes' de la ficha")
        params = set((ficha.get("parametros") or {}).keys())
        for p in parametros_en_sql(sql):
            if p not in params:
                inf.error(rel(carpeta / consulta), f"usa el parámetro @{p}, que no está en 'parametros' de la ficha")


def validar_agente(carpeta: Path, ficha: dict, inf: Informe):
    archivos = ficha.get("archivos") or {}
    instr = carpeta / archivos.get("instrucciones", "agente.md")
    if not instr.exists():
        return
    fm, cuerpo = leer_frontmatter(instr)
    if fm is None:
        inf.error(rel(instr), "falta el encabezado --- con name y description")
        return
    if fm.get("name") != ficha.get("id"):
        inf.error(rel(instr), f"name '{fm.get('name')}' debe ser igual al id '{ficha.get('id')}'")
    desc = str(fm.get("description", "")).strip()
    if not desc or desc.startswith("["):
        inf.error(rel(instr), "falta description")
    if "model" in fm and fm["model"] not in MODELOS_SUBAGENTE:
        inf.error(rel(instr), f"model '{fm['model']}' no es válido; usa {sorted(MODELOS_SUBAGENTE)}")
    for s in ficha.get("usa_skills") or []:
        if s not in cuerpo:
            inf.aviso(rel(instr), f"las instrucciones no mencionan la skill '{s}'")


def validar_tablero(carpeta: Path, ficha: dict, fichas: dict, inf: Informe):
    definicion = carpeta / (ficha.get("archivos") or {}).get("definicion", "tablero.yaml")
    if not definicion.exists():
        return
    tablero = leer_yaml(definicion) or {}
    usa = set(ficha.get("usa_skills") or [])
    for seccion in tablero.get("secciones") or []:
        refs = [t.get("indicador") for t in seccion.get("tarjetas") or []]
        refs += [g.get("indicador") for g in seccion.get("graficos") or []]
        for ref in filter(None, refs):
            if "." not in ref:
                inf.error(rel(definicion), f"indicador '{ref}' debe tener la forma skill.indicador")
                continue
            skill, ind = ref.split(".", 1)
            if skill not in usa:
                inf.error(rel(definicion), f"usa la skill '{skill}', que no está en 'usa_skills' del artefacto")
            ids = {i.get("id") for i in (fichas.get(skill, {}).get("indicadores") or [])}
            if skill in fichas and ind not in ids:
                inf.error(rel(definicion), f"la skill '{skill}' no tiene el indicador '{ind}'")
        for tabla in seccion.get("tablas") or []:
            if tabla.get("fuente") not in usa:
                inf.error(rel(definicion), f"la tabla usa '{tabla.get('fuente')}', que no está en 'usa_skills'")


def validar_versiones(dir_cliente: Path, carpetas: dict, fichas: dict, base: str, inf: Informe):
    try:
        cambiados = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD", "--", str(dir_cliente)],
            cwd=RAIZ, capture_output=True, text=True, check=True,
        ).stdout.split()
    except subprocess.CalledProcessError as e:
        inf.aviso(rel(dir_cliente), f"no se pudo comparar con {base}: {e.stderr.strip()}")
        return
    for cid, carpeta in carpetas.items():
        prefijo = rel(carpeta) + "/"
        if not any(c.startswith(prefijo) for c in cambiados):
            continue
        ficha_rel = rel(carpeta / "componente.yaml")
        anterior = subprocess.run(["git", "show", f"{base}:{ficha_rel}"], cwd=RAIZ, capture_output=True, text=True)
        if anterior.returncode != 0:
            continue  # componente nuevo
        v_ant = (yaml.safe_load(anterior.stdout) or {}).get("version")
        v_nueva = fichas[cid].get("version")
        if v_ant == v_nueva:
            inf.error(rel(carpeta), f"cambió pero su versión sigue en {v_nueva}; súbela y explica el cambio en notas_version")
        elif _tupla(v_nueva) < _tupla(v_ant):
            inf.error(rel(carpeta), f"la versión bajó de {v_ant} a {v_nueva}")


def _tupla(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def validar_bigquery(manifiesto: dict, carpetas: dict, fichas: dict, inf: Informe):
    try:
        from google.cloud import bigquery
    except ImportError:
        inf.error("bigquery", "falta el paquete google-cloud-bigquery (pip install -r herramientas/requirements.txt)")
        return
    proyecto = (manifiesto.get("gcp") or {}).get("proyecto_consultas")
    limite = (manifiesto.get("eco") or {}).get("limite_bytes_por_consulta")
    cliente = bigquery.Client(project=proyecto)
    for cid, ficha in fichas.items():
        consulta = (ficha.get("archivos") or {}).get("consulta")
        if ficha.get("tipo") != "skill" or not consulta:
            continue
        ruta = carpetas[cid] / consulta
        params = []
        for nombre, valor in (ficha.get("parametros") or {}).items():
            tipo = "INT64" if isinstance(valor, int) else "FLOAT64" if isinstance(valor, float) else "STRING"
            params.append(bigquery.ScalarQueryParameter(nombre, tipo, valor))
        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=params,
                                      labels={"uso": "exek-validacion", "cliente": manifiesto.get("cliente_id", "")})
        try:
            job = cliente.query(ruta.read_text(encoding="utf-8"), job_config=cfg)
            gb = job.total_bytes_processed / 1e9
            print(f"  BigQuery OK  {rel(ruta)}  ({gb:.2f} GB por ejecución)")
            if limite and job.total_bytes_processed > limite:
                inf.error(rel(ruta), f"procesaría {gb:.2f} GB, más que el límite del cliente ({limite / 1e9:.2f} GB)")
        except Exception as e:  # noqa: BLE001
            inf.error(rel(ruta), f"BigQuery rechazó la consulta: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida el almacén de componentes de un cliente.")
    ap.add_argument("clientes", nargs="+", type=Path, help="Carpetas de clientes, por ejemplo clientes/districash")
    ap.add_argument("--bigquery", action="store_true", help="Revisa los SQL en BigQuery (modo de prueba)")
    ap.add_argument("--base", help="Referencia git para exigir que los componentes cambiados suban su versión")
    args = ap.parse_args()

    total_errores = 0
    for dir_cliente in args.clientes:
        print(f"\n== Validando {rel(dir_cliente)} ==")
        if not dir_cliente.is_dir():
            print(f"  ERROR  {dir_cliente} no es una carpeta")
            total_errores += 1
            continue
        inf = validar_cliente(dir_cliente, args.bigquery, args.base)
        for a in inf.avisos:
            print(f"  AVISO  {a}")
        for e in inf.errores:
            print(f"  ERROR  {e}")
        print(f"  {'OK' if not inf.errores else 'FALLÓ'}: {len(inf.errores)} errores, {len(inf.avisos)} avisos")
        total_errores += len(inf.errores)
    return 1 if total_errores else 0


if __name__ == "__main__":
    sys.exit(main())
