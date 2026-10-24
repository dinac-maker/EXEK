"""Conexión de la Consola Exek con el repositorio en GitHub.

La consola escribe en GitHub en dos casos: la solicitud de cambio con la carpeta de un
cliente nuevo (consola/alta.py) y la etiqueta de cada versión que se publica. Usa una
llave de permisos mínimos guardada en Secret Manager (decisión del 23/10/2026).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

REPOSITORIO = os.environ.get("CONSOLA_REPOSITORIO", "dinac-maker/EXEK")
SECRETO_GITHUB = "projects/exekai/secrets/github-consola-exek/versions/latest"


class GitHubApagado(RuntimeError):
    """En modo demostración la consola no escribe en GitHub."""


def apagado() -> bool:
    return os.environ.get("CONSOLA_GITHUB") == "apagado"


def llave() -> str:
    if apagado():
        raise GitHubApagado("en modo demostración la consola no escribe en GitHub")
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient().access_secret_version(
        name=SECRETO_GITHUB).payload.data.decode().strip()


def llamar(metodo: str, ruta: str, llave_: str, cuerpo: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORIO}{ruta}", method=metodo,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Authorization": f"Bearer {llave_}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "consola-exek"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


TIPO_EN_ETIQUETA = {"skill": "skill", "agente": "agente", "artefacto": "artefacto", "plugin": "plugin"}


def nombre_etiqueta(cliente_id: str, tipo: str, componente_id: str, numero: str) -> str:
    """districash/skill/deteccion-clientes-perdidos/v0.2.2

    Lleva el cliente adelante porque dos clientes pueden tener un componente con el mismo id."""
    return f"{cliente_id}/{TIPO_EN_ETIQUETA[tipo]}/{componente_id}/v{numero}"


def etiquetar_version(cliente_id: str, tipo: str, componente_id: str, nombre: str, numero: str, commit: str,
                      quien: str, llamar_=None) -> tuple[str, bool]:
    """Crea en GitHub la etiqueta de una versión publicada, sobre el commit de esa versión.

    Devuelve (nombre de la etiqueta, True si se creó ahora / False si ya existía). Una
    versión se etiqueta una sola vez: si se vuelve a publicar después, la etiqueta ya está."""
    llamar_ = llamar_ or llamar
    k = llave()
    etiqueta = nombre_etiqueta(cliente_id, tipo, componente_id, numero)
    try:
        llamar_("GET", f"/git/ref/tags/{urllib.parse.quote(etiqueta)}", k)
        return etiqueta, False
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    sha = llamar_("GET", f"/commits/{commit}", k)["sha"]  # el registro guarda el commit corto
    objeto = llamar_("POST", "/git/tags", k, {
        "tag": etiqueta, "object": sha, "type": "commit",
        "message": f"{nombre} {numero} publicada en producción para {cliente_id} desde la Consola Exek por {quien}.",
    })
    try:
        llamar_("POST", "/git/refs", k, {"ref": f"refs/tags/{etiqueta}", "sha": objeto["sha"]})
    except urllib.error.HTTPError as e:
        if e.code == 422:  # otra persona la creó en el mismo momento
            return etiqueta, False
        raise
    return etiqueta, True
