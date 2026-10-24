"""Envío de alertas por correo desde alertas@exek.co (fase 4, decisión C del 24/10/2026).

Se usa la API de Gmail con la cuenta correo-exek, que tiene delegación de Google Workspace
solo para enviar (gmail.send). ECO firma a nombre de esa cuenta con IAM, sin descargar
llaves (eco-prueba tiene el rol Creador de tokens sobre correo-exek).

ECO_CORREO=apagado no envía nada (pruebas y computador del autor).
"""
from __future__ import annotations

import base64
import html
import os
import re
from email.message import EmailMessage
from email.utils import formataddr

REMITENTE = os.environ.get("ECO_CORREO_REMITENTE", "alertas@exek.co")
CUENTA_CORREO = os.environ.get("ECO_CORREO_CUENTA", "correo-exek@exekai.iam.gserviceaccount.com")
ALCANCE = "https://www.googleapis.com/auth/gmail.send"


class CorreoApagado(RuntimeError):
    pass


def apagado() -> bool:
    return os.environ.get("ECO_CORREO") == "apagado"


def _en_linea(texto: str) -> str:
    t = html.escape(texto)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def a_html(texto: str) -> str:
    """Convierte el Markdown sencillo que escribe ECO (títulos, negritas, listas y tablas) a HTML."""
    partes, tabla, lista = [], [], []

    def cerrar():
        if tabla:
            filas = [f for f in tabla if not re.match(r"^\s*\|?\s*:?-{2,}", f)]
            celdas = [[c.strip() for c in f.strip().strip("|").split("|")] for f in filas]
            if celdas:
                cab = "".join(f'<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #ccc">{_en_linea(c)}</th>' for c in celdas[0])
                cuerpo = "".join("<tr>" + "".join(f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{_en_linea(c)}</td>' for c in f) + "</tr>"
                                 for f in celdas[1:])
                partes.append(f'<table style="border-collapse:collapse;font-size:13px"><tr>{cab}</tr>{cuerpo}</table>')
            tabla.clear()
        if lista:
            partes.append("<ul>" + "".join(f"<li>{_en_linea(x)}</li>" for x in lista) + "</ul>")
            lista.clear()

    for linea in texto.splitlines():
        s = linea.strip()
        if s.startswith("|"):
            if lista:
                cerrar()
            tabla.append(s)
            continue
        if s.startswith(("- ", "* ")):
            if tabla:
                cerrar()
            lista.append(s[2:])
            continue
        cerrar()
        if not s:
            continue
        if s.startswith("#"):
            partes.append(f"<h3>{_en_linea(s.lstrip('#').strip())}</h3>")
        else:
            partes.append(f"<p>{_en_linea(s)}</p>")
    cerrar()
    return "\n".join(partes)


def armar_mensaje(para: list[str], asunto: str, texto: str, cliente_nombre: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = formataddr(("Alertas I-NA · Exek", REMITENTE))
    m["To"] = ", ".join(para)
    m["Subject"] = asunto
    pie = (f"Alerta automática de I-NA para {cliente_nombre}. El resultado también queda guardado en la plataforma.")
    m.set_content(f"{texto}\n\n--\n{pie}")
    m.add_alternative(
        f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#1f2230">{a_html(texto)}'
        f'<p style="color:#5f6372;font-size:12px;margin-top:24px">{html.escape(pie)}</p></div>', subtype="html")
    return m


def _credenciales():
    import google.auth
    from google.auth import iam
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    propias, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    firmante = iam.Signer(Request(), propias, CUENTA_CORREO)
    return service_account.Credentials(firmante, CUENTA_CORREO, "https://oauth2.googleapis.com/token",
                                       scopes=[ALCANCE], subject=REMITENTE)


def enviar(para: list[str], asunto: str, texto: str, cliente_nombre: str) -> None:
    if apagado():
        raise CorreoApagado("el envío de correo está apagado (ECO_CORREO=apagado)")
    if not para:
        raise ValueError("no hay destinatarios")
    from google.auth.transport.requests import AuthorizedSession

    mensaje = armar_mensaje(para, asunto, texto, cliente_nombre)
    crudo = base64.urlsafe_b64encode(mensaje.as_bytes()).decode()
    r = AuthorizedSession(_credenciales()).post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": crudo}, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"Gmail respondió {r.status_code}: {r.text[:300]}")
