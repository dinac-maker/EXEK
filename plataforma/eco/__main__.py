"""ECO desde la terminal.

Uso (desde la carpeta plataforma/):
    python -m eco "¿Cuántos clientes perdidos tenemos?"
    python -m eco                      conversación: escribe preguntas hasta "salir"
    python -m eco --detalle "..."      muestra además skills, consultas, tokens y costo
    python -m eco --modo produccion --usuario comercial.demo@exek.co "..."
                                       como lo vería ese usuario: versiones publicadas y solo lo de su rol
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from eco.configuracion import cargar_cliente
from eco.motor import Respuesta, SesionEco
from eco.paquete import armar


def mostrar(r: Respuesta, detalle: bool) -> None:
    print(r.texto)
    if detalle or not r.ok:
        print("\n---")
        print("Componentes:", ", ".join(f"{c['id']} v{c['version']}" for c in r.componentes) or "ninguno")
        for c in r.consultas:
            if c.get("rechazada"):
                print(f"Consulta rechazada ({c['componente']}): {c['motivo']}")
            else:
                print(f"Consulta {c['componente']}: {c['filas_total']} filas, "
                      f"{(c['bytes_procesados'] or 0) / 1e9:.2f} GB, trabajo {c['job_id']}")
        print("Tokens:", r.tokens)
        if r.costo_usd_estimado is not None:
            print(f"Costo estimado: USD {r.costo_usd_estimado:.4f}  ·  {r.duracion_ms / 1000:.1f} s")
        if r.error:
            print("Error:", r.error)


async def principal(args) -> int:
    usuario = args.usuario or os.environ.get("ECO_USUARIO") or getpass.getuser()
    if args.modo == "produccion":
        from eco.acceso import AccesoRegistro, SinAcceso

        try:
            at = AccesoRegistro().atender(usuario)
        except SinAcceso as e:
            print(e)
            return 1
        cliente = at.cliente
        print(f"Modo producción · {at.usuario} · rol {at.rol} · "
              + ", ".join(f"{c['id']} v{c['version']}" for c in at.paquete.componentes))
        sesion_eco = SesionEco(at.cliente, at.paquete, at.usuario, modo="produccion", rol=at.rol,
                               credenciales=at.credenciales, cuenta_datos=at.cuenta_datos)
    else:
        cliente = cargar_cliente(args.cliente)
        sesion_eco = SesionEco(cliente, armar(cliente), usuario)
    async with sesion_eco as sesion:
        if args.pregunta:
            r = await sesion.preguntar(" ".join(args.pregunta))
            mostrar(r, args.detalle)
            return 0 if r.ok else 1
        print(f"ECO de {cliente.nombre} (escribe 'salir' para terminar)")
        while True:
            try:
                pregunta = input("\nTú: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if pregunta.lower() in ("salir", "exit", "quit"):
                break
            if pregunta:
                print("\nECO: ", end="")
                mostrar(await sesion.preguntar(pregunta), args.detalle)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m eco", description="ECO de prueba desde la terminal.")
    ap.add_argument("pregunta", nargs="*")
    ap.add_argument("--cliente", default="districash")
    ap.add_argument("--usuario", help="Quién pregunta (queda en el registro; en producción, su correo registrado)")
    ap.add_argument("--modo", choices=["prueba", "produccion"], default="prueba",
                    help="prueba: almacén del repositorio completo (por defecto); produccion: lo publicado para el rol del usuario")
    ap.add_argument("--detalle", action="store_true", help="Muestra componentes, consultas, tokens y costo")
    return asyncio.run(principal(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
