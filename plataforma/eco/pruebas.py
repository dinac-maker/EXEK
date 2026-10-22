"""Pruebas de ECO con los casos del cliente (clientes/<cliente>/pruebas/casos.yaml).

Uso (desde la carpeta plataforma/):
    python -m eco.pruebas                      todos los casos de Districash
    python -m eco.pruebas --cliente districash --caso 1

Por cada caso revisa:
- debe_usar: que ECO haya usado esos skills o agentes.
- debe_mencionar: que la respuesta tenga esas frases (sin importar mayúsculas ni tildes;
  también vale si aparecen todas sus palabras).
- no_debe: que no haya corrido consultas que cambien los parámetros acordados.
- fecha de corte y cifras: que la respuesta diga la fecha de corte y, si usó un skill con
  cifra de referencia, que la cifra coincida con la que da BigQuery directamente.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
import unicodedata

import yaml

from eco.configuracion import RAIZ, cargar_cliente
from eco.consultas import ConsultasBigQuery
from eco.motor import SesionEco
from eco.paquete import armar

# Cifra que debe aparecer en la respuesta cuando ECO usa el skill: columna del resultado.
CIFRAS_DE_REFERENCIA = {
    "deteccion-clientes-perdidos": ["clientes_perdidos"],
}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.lower())


def menciona(texto: str, frase: str) -> bool:
    t, f = normalizar(texto), normalizar(frase)
    if f in t:
        return True
    palabras = [p for p in re.findall(r"\w+", f) if len(p) > 3 or p.isdigit()]
    return bool(palabras) and all(re.search(rf"\b{re.escape(p)}", t) for p in palabras)


def formas_de_numero(n: float) -> list[str]:
    entero = int(round(n))
    con_puntos = f"{entero:,}".replace(",", ".")
    return [con_puntos, f"{entero:,}", str(entero)]


def formas_de_fecha(fecha: dt.date) -> list[str]:
    return [fecha.strftime("%d/%m/%Y"), f"{fecha.day}/{fecha.month}/{fecha.year}",
            f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}", fecha.isoformat()]


def contiene_alguna(texto: str, formas: list[str]) -> bool:
    t = normalizar(texto)
    return any(re.search(rf"(?<![\d.,]){re.escape(normalizar(f))}(?![\d]|[.,]\d)", t) for f in formas)


def referencias(cliente, paquete) -> tuple[dt.date | None, dict]:
    """Corre las consultas de los skills directamente para tener las cifras de referencia."""
    bq = ConsultasBigQuery(cliente, paquete)
    fecha_corte, cifras = None, {}
    for sid in paquete.skills:
        r = bq.ejecutar_skill(sid, 1)
        fila = (r["filas"] or [{}])[0]
        if fila.get("fecha_corte"):
            fecha_corte = dt.date.fromisoformat(str(fila["fecha_corte"])[:10])
        cifras[sid] = {col: fila.get(col) for col in CIFRAS_DE_REFERENCIA.get(sid, [])}
    return fecha_corte, cifras


def revisar(caso: dict, r, paquete, fecha_corte, cifras) -> list[str]:
    fallas = []
    usados = {c["id"] for c in r.componentes}
    if not r.ok:
        fallas.append(f"ECO no completó la respuesta: {r.error}")
    for cid in caso.get("debe_usar") or []:
        if cid not in usados:
            fallas.append(f"no usó {cid} (usó: {', '.join(sorted(usados)) or 'nada'})")
    for frase in caso.get("debe_mencionar") or []:
        if not menciona(r.texto, frase):
            fallas.append(f"no menciona «{frase}»")
    if caso.get("no_debe"):
        for c in r.consultas:
            sid = c.get("componente")
            if sid in paquete.skills and c.get("parametros"):
                acordados = {k: v for k, v in paquete.skills[sid].parametros.items() if k in c["parametros"]}
                if c["parametros"] != acordados:
                    fallas.append(f"corrió {sid} con parámetros distintos a los acordados: {c['parametros']}")
            if sid == "consulta-libre" and re.search(r"\b30\b", c.get("sql", "")):
                fallas.append("corrió una consulta libre con 30 días (posible cambio de definición)")
    if fecha_corte and usados and not contiene_alguna(r.texto, formas_de_fecha(fecha_corte)):
        fallas.append(f"no dice la fecha de corte ({fecha_corte:%d/%m/%Y})")
    for sid in usados & set(cifras):
        for col, valor in cifras[sid].items():
            if valor is not None and not contiene_alguna(r.texto, formas_de_numero(float(valor))):
                fallas.append(f"la cifra {col} = {formas_de_numero(float(valor))[0]} no aparece en la respuesta")
    return fallas


async def principal(args) -> int:
    cliente = cargar_cliente(args.cliente)
    paquete = armar(cliente)
    casos = yaml.safe_load((cliente.carpeta / "pruebas" / "casos.yaml").read_text(encoding="utf-8"))["casos"]
    if args.caso:
        casos = [casos[args.caso - 1]]

    print(f"Pruebas de ECO · {cliente.nombre} · {len(casos)} casos\n")
    fecha_corte, cifras = referencias(cliente, paquete)
    print(f"Referencia BigQuery: fecha de corte {fecha_corte:%d/%m/%Y}; cifras {cifras}\n")

    resultados, costo = [], 0.0
    for i, caso in enumerate(casos, 1):
        # Cada caso es una conversación nueva.
        async with SesionEco(cliente, paquete, "pruebas-automaticas") as sesion:
            r = await sesion.preguntar(caso["pregunta"])
        fallas = revisar(caso, r, paquete, fecha_corte, cifras)
        costo += r.costo_usd_estimado or 0
        estado = "PASA" if not fallas else "FALLA"
        print(f"[{estado}] {i}. {caso['pregunta']}")
        print(f"        usó: {', '.join(c['id'] for c in r.componentes) or 'nada'} · "
              f"{len(r.consultas)} consultas · {r.duracion_ms / 1000:.0f} s · USD {r.costo_usd_estimado or 0:.3f}")
        for f in fallas:
            print(f"        - {f}")
        if args.respuestas or fallas:
            print("        respuesta: " + r.texto.replace("\n", "\n                   "))
        resultados.append({"caso": i, "pregunta": caso["pregunta"], "pasa": not fallas, "fallas": fallas,
                           "componentes": r.componentes, "costo_usd_estimado": r.costo_usd_estimado,
                           "respuesta": r.texto})

    pasan = sum(x["pasa"] for x in resultados)
    print(f"\nResultado: {pasan} de {len(resultados)} casos pasan · costo estimado USD {costo:.3f}")
    salida = RAIZ / ".eco" / f"pruebas-{cliente.cliente_id}-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps({"cliente": cliente.cliente_id, "fecha_corte": fecha_corte, "cifras": cifras,
                                  "resultados": resultados}, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(f"Detalle guardado en {salida.relative_to(RAIZ)}")
    return 0 if pasan == len(resultados) else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m eco.pruebas", description="Corre los casos de prueba contra ECO.")
    ap.add_argument("--cliente", default="districash")
    ap.add_argument("--caso", type=int, help="Número del caso (1, 2, ...); por defecto, todos")
    ap.add_argument("--respuestas", action="store_true", help="Muestra todas las respuestas, no solo las que fallan")
    return asyncio.run(principal(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
