"""Carga inicial del registro: crea las tablas y registra a Districash.

Uso (desde la carpeta plataforma/):
    python -m registro.carga_inicial                       registro real (exekai.exek_registro)
    python -m registro.carga_inicial --dataset otro         otro dataset, por ejemplo de pruebas
    python -m registro.carga_inicial --en-memoria           solo muestra lo que haría

Se puede correr varias veces: lo que ya existe no se duplica.

- Cliente, etiquetas y roles: los acordados en docs/definiciones.md (secciones 7.1 y 7.8).
- Componentes y versiones: se leen del historial de Git de clientes/districash/.
- Etiquetas y visibilidad de cada componente: sección 7.3 y fichas 7.4 a 7.7.
- Cada componente queda publicado en su versión más reciente (la que ya usa ECO).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

from registro.almacen import AlmacenBigQuery, AlmacenMemoria
from registro.servicio import ErrorRegistro, Registro, identificador

RAIZ = Path(__file__).resolve().parents[2]
QUIEN = "carga-inicial"

DISTRICASH = {
    "cliente_id": "districash",
    "nombre": "Districash",
    "dominios": ["exek.co"],  # Districash es la empresa demo de Exek
    "proyecto_datos": "exek-produccion",
    "dataset": "NewtonAgentSpace",
    "etiquetas": ["Ventas", "Compras", "Inventarios", "Producción", "Consumos", "Gerencia"],
    "roles": {
        "Gerencia": ["Gerencia", "Ventas", "Compras", "Inventarios", "Producción", "Consumos"],
        "Comercial": ["Ventas"],
        "Compras": ["Compras", "Inventarios"],
    },
    "componentes": {
        "deteccion-clientes-perdidos": {"etiquetas": ["Ventas"], "visible_portal": False},
        "indicadores-ventas": {"etiquetas": ["Ventas"], "visible_portal": False},
        "monitor-clientes-perdidos": {"etiquetas": ["Ventas"], "visible_portal": True},
        "tablero-control-gerencia": {"etiquetas": ["Gerencia"], "visible_portal": True},
    },
}

CARPETAS_TIPO = {"skills": "skill", "agentes": "agente", "artefactos": "artefacto", "plugins": "plugin"}


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8").stdout


def versiones_en_git(carpeta: Path) -> list[dict]:
    """Primera aparición de cada versión de un componente en el historial de Git."""
    rel = carpeta.relative_to(RAIZ).as_posix()
    vistas, salida = set(), []
    for linea in _git("log", "--reverse", "--format=%h|%an", "--", rel).splitlines():
        commit, autor = linea.split("|", 1)
        texto = _git("show", f"{commit}:{rel}/componente.yaml")
        if not texto:
            continue
        ficha = yaml.safe_load(texto) or {}
        numero = str(ficha.get("version", ""))
        if numero and numero not in vistas:
            vistas.add(numero)
            salida.append({"numero": numero, "commit": commit, "notas": ficha.get("notas_version"),
                           "autor": ficha.get("autor") or autor, "nombre": ficha.get("nombre"),
                           "tipo": ficha.get("tipo")})
    return salida


def cargar(reg: Registro, datos: dict = DISTRICASH) -> None:
    cid = datos["cliente_id"]
    if reg.almacen.obtener("clientes", cliente_id=cid) is None:
        reg.crear_cliente(QUIEN, datos["nombre"], datos["dominios"], datos["proyecto_datos"], datos["dataset"], cid)
        print(f"Cliente {datos['nombre']} creado")
    existentes = {e["etiqueta_id"] for e in reg.etiquetas(cid)}
    for nombre in datos["etiquetas"]:
        if identificador(nombre) not in existentes:
            reg.crear_etiqueta(QUIEN, cid, nombre)
            print(f"  etiqueta {nombre}")
    roles = {r["rol_id"] for r in reg.roles(cid)}
    for nombre, etiquetas in datos["roles"].items():
        if identificador(nombre) not in roles:
            reg.crear_rol(QUIEN, cid, nombre, [identificador(e) for e in etiquetas])
            print(f"  rol {nombre}: {', '.join(etiquetas)}")

    carpeta_cliente = RAIZ / "clientes" / cid
    for carpeta_tipo, tipo in CARPETAS_TIPO.items():
        for carpeta in sorted(p for p in (carpeta_cliente / carpeta_tipo).glob("*") if p.is_dir()):
            comp_id = carpeta.name
            for v in versiones_en_git(carpeta):
                if reg.registrar_version(cid, comp_id, v["tipo"] or tipo, v["nombre"] or comp_id, v["numero"],
                                         v["commit"], v["notas"], v["autor"], quien=QUIEN):
                    print(f"  {comp_id} {v['numero']} ({v['commit']})")
            conf = datos["componentes"].get(comp_id)
            comp = reg.componente(cid, comp_id)
            if conf and (sorted(comp["etiquetas"]) != sorted(identificador(e) for e in conf["etiquetas"])
                         or comp["visible_portal"] != conf["visible_portal"]):
                comp = reg.configurar_componente(QUIEN, cid, comp_id, comp["revision"],
                                                 etiquetas=[identificador(e) for e in conf["etiquetas"]],
                                                 visible_portal=conf["visible_portal"])
            ultima = reg.versiones(cid, comp_id)[0]["numero"]
            if comp["version_produccion"] is None:
                reg.publicar(QUIEN, cid, comp_id, ultima, comp["revision"])
                print(f"  {comp_id}: publicada {ultima}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m registro.carga_inicial")
    ap.add_argument("--proyecto", default="exekai")
    ap.add_argument("--dataset", default="exek_registro")
    ap.add_argument("--en-memoria", action="store_true", help="No escribe en BigQuery; solo muestra el resultado")
    args = ap.parse_args()

    almacen = AlmacenMemoria() if args.en_memoria else AlmacenBigQuery(args.proyecto, args.dataset)
    almacen.preparar()
    reg = Registro(almacen)
    try:
        cargar(reg)
    except ErrorRegistro as e:
        print(f"ERROR: {e}")
        return 1
    print("\nResumen:")
    for c in reg.componentes("districash"):
        print(f"  {c['componente_id']}: v{c['version_produccion']} · etiquetas {c['etiquetas']} · portal {c['visible_portal']}")
    for r in reg.roles("districash"):
        ve = [c["componente_id"] for c in reg.permitidos_para_rol("districash", r["rol_id"])]
        print(f"  rol {r['nombre']} ve: {', '.join(ve) or 'nada'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
