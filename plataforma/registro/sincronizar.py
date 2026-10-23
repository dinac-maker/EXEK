"""Registra como "en prueba" las versiones nuevas que GitHub dejó en Cloud Storage.

La consola lo hace sola al abrir el almacén de un cliente; también se puede correr a mano.

Uso (desde la carpeta plataforma/):
    python -m registro.sincronizar                         Districash, registro real
    python -m registro.sincronizar --respaldar-historial   además guarda en Cloud Storage
                                                           el paquete de las versiones viejas
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from registro.almacen import AlmacenBigQuery
from registro.paquetes import BUCKET, Paquetes, PaquetesGCS, armar_desde_git
from registro.servicio import SISTEMA_GITHUB, Registro


def sincronizar(reg: Registro, paquetes: Paquetes, cliente_id: str) -> list[tuple[str, str]]:
    """Devuelve las versiones registradas ahora: [(componente_id, numero), ...]."""
    conocidas = {(v["componente_id"], v["numero"]) for v in reg.almacen.listar("versiones", cliente_id=cliente_id)}
    nuevas = []
    for m in paquetes.manifiestos(cliente_id):
        commit = m.get("commit")
        for comp in m.get("componentes", []):
            clave = (comp["id"], str(comp["version"]))
            if clave in conocidas:
                continue
            reg.registrar_version(cliente_id, comp["id"], comp["tipo"], comp["nombre"], str(comp["version"]),
                                  commit, comp.get("notas_version"), comp.get("autor"),
                                  paquetes.uri(cliente_id, commit), quien=SISTEMA_GITHUB)
            conocidas.add(clave)
            nuevas.append(clave)
    return nuevas


def respaldar_historial(reg: Registro, paquetes: Paquetes, cliente_id: str) -> list[str]:
    """Guarda el paquete de cada commit con versiones registradas que aún no lo tenga."""
    commits = sorted({v["commit"] for v in reg.almacen.listar("versiones", cliente_id=cliente_id)})
    guardados = []
    with tempfile.TemporaryDirectory() as tmp:
        for commit in commits:
            if paquetes.existe(cliente_id, commit):
                continue
            zip_local, manifiesto = armar_desde_git(cliente_id, commit, Path(tmp))
            paquetes.subir(cliente_id, commit, zip_local, manifiesto)
            guardados.append(commit)
    return guardados


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m registro.sincronizar")
    ap.add_argument("--cliente", default="districash")
    ap.add_argument("--proyecto", default="exekai")
    ap.add_argument("--dataset", default="exek_registro")
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--respaldar-historial", action="store_true")
    args = ap.parse_args()

    reg = Registro(AlmacenBigQuery(args.proyecto, args.dataset))
    paquetes = PaquetesGCS(args.bucket)
    if args.respaldar_historial:
        for c in respaldar_historial(reg, paquetes, args.cliente):
            print(f"Paquete guardado: {paquetes.uri(args.cliente, c)}")
    nuevas = sincronizar(reg, paquetes, args.cliente)
    print("\n".join(f"Nueva versión en prueba: {c} {n}" for c, n in nuevas) or "No hay versiones nuevas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
