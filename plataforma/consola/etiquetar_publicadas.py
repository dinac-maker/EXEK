"""Crea en GitHub la etiqueta de las versiones que ya están en producción.

Sirve para las versiones publicadas antes de que la consola creara etiquetas (por
ejemplo, las de la carga inicial). Las que ya tienen etiqueta no se tocan.

Uso (desde la carpeta plataforma/):
    python -m consola.etiquetar_publicadas                  muestra qué etiquetas faltan
    python -m consola.etiquetar_publicadas --crear          las crea en GitHub
"""
from __future__ import annotations

import argparse
import sys

from consola import github
from registro.almacen import AlmacenBigQuery
from registro.servicio import Registro


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m consola.etiquetar_publicadas")
    ap.add_argument("--crear", action="store_true", help="Crea las etiquetas (sin esto solo las muestra)")
    ap.add_argument("--quien", default="carga-inicial", help="Quién publicó, para el mensaje de la etiqueta")
    args = ap.parse_args()

    reg = Registro(AlmacenBigQuery("exekai", "exek_registro"))
    for c in reg.clientes():
        for comp in reg.almacen_completo(c["cliente_id"]):
            if comp["estado"] != "activo" or not comp["version_produccion"]:
                continue
            v = next(v for v in comp["versiones"] if v["numero"] == comp["version_produccion"])
            nombre = github.nombre_etiqueta(c["cliente_id"], comp["tipo"], comp["componente_id"], v["numero"])
            if not args.crear:
                print(f"{nombre}  (commit {v['commit']})")
                continue
            etiqueta, nueva = github.etiquetar_version(c["cliente_id"], comp["tipo"], comp["componente_id"],
                                                       comp["nombre"], v["numero"], v["commit"], args.quien)
            if nueva:
                reg._anotar(args.quien, "version", "etiquetar", f"Etiqueta en Git: {etiqueta}", c["cliente_id"],
                            comp["componente_id"], despues={"etiqueta": etiqueta, "commit": v["commit"]})
            print(("Creada: " if nueva else "Ya existía: ") + etiqueta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
