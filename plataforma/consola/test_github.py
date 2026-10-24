"""Pruebas de las etiquetas de versión en Git (sin llamar a GitHub).

Uso (desde la carpeta plataforma/): python -m pytest consola/test_github.py
"""
from __future__ import annotations

import io
import urllib.error
import urllib.parse

import pytest

from consola import github


class GitHubFalso:
    """Imita las llamadas a la API de GitHub que usa la consola."""

    def __init__(self, etiquetas_existentes=()):
        self.etiquetas = set(etiquetas_existentes)
        self.llamadas = []

    def __call__(self, metodo, ruta, llave, cuerpo=None):
        self.llamadas.append((metodo, ruta, cuerpo))
        if metodo == "GET" and ruta.startswith("/git/ref/tags/"):
            if urllib.parse.unquote(ruta[len("/git/ref/tags/"):]) in self.etiquetas:
                return {"ref": ruta}
            raise urllib.error.HTTPError(ruta, 404, "Not Found", {}, io.BytesIO(b""))
        if metodo == "GET" and ruta.startswith("/commits/"):
            return {"sha": ruta.split("/")[-1] + "0" * 33}
        if metodo == "POST" and ruta == "/git/tags":
            return {"sha": "objeto-etiqueta"}
        if metodo == "POST" and ruta == "/git/refs":
            self.etiquetas.add(cuerpo["ref"][len("refs/tags/"):])
            return {}
        raise AssertionError(f"llamada inesperada {metodo} {ruta}")


@pytest.fixture(autouse=True)
def llave_falsa(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "llave-de-prueba")
    monkeypatch.delenv("CONSOLA_GITHUB", raising=False)


def test_nombre_lleva_el_cliente():
    assert github.nombre_etiqueta("districash", "skill", "deteccion-clientes-perdidos", "0.2.2") == \
        "districash/skill/deteccion-clientes-perdidos/v0.2.2"


def test_crea_la_etiqueta_sobre_el_commit_de_la_version():
    gh = GitHubFalso()
    etiqueta, nueva = github.etiquetar_version("districash", "skill", "deteccion-clientes-perdidos",
                                               "Detección de clientes perdidos", "0.2.2", "66ca0fe",
                                               "dina.silva@exek.co", llamar_=gh)
    assert nueva and etiqueta == "districash/skill/deteccion-clientes-perdidos/v0.2.2"
    objeto = next(c for m, r, c in gh.llamadas if r == "/git/tags")
    assert objeto["object"].startswith("66ca0fe") and len(objeto["object"]) == 40
    assert "dina.silva@exek.co" in objeto["message"]
    assert ("POST", "/git/refs", {"ref": f"refs/tags/{etiqueta}", "sha": "objeto-etiqueta"}) in gh.llamadas


def test_no_repite_una_etiqueta_existente():
    gh = GitHubFalso({"districash/agente/monitor-clientes-perdidos/v0.2.0"})
    etiqueta, nueva = github.etiquetar_version("districash", "agente", "monitor-clientes-perdidos",
                                               "Monitor de clientes perdidos", "0.2.0", "84db223", "x", llamar_=gh)
    assert not nueva
    assert not any(m == "POST" for m, _r, _c in gh.llamadas)


def test_en_demostracion_no_escribe(monkeypatch):
    monkeypatch.setenv("CONSOLA_GITHUB", "apagado")
    with pytest.raises(github.GitHubApagado):
        github.etiquetar_version("districash", "skill", "x", "X", "1.0.0", "abc1234", "x", llamar_=GitHubFalso())
