"""Quién está usando la consola.

En Cloud Run, la consola está detrás de Identity-Aware Proxy (IAP): solo entra el grupo
consola@exek.co, e IAP manda en cada petición un token firmado con el correo de la
persona. La consola verifica la firma (así nadie puede inventarse el correo).

En el computador del autor no hay IAP: se usa CONSOLA_USUARIO_LOCAL.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

AUDIENCIA_IAP = os.environ.get("CONSOLA_IAP_AUDIENCIA")  # /projects/<num>/locations/<región>/services/<servicio>
USUARIO_LOCAL = os.environ.get("CONSOLA_USUARIO_LOCAL", "local@exek.co")
CERTIFICADOS_IAP = "https://www.gstatic.com/iap/verify/public_key"


def usuario_actual(request: Request) -> str:
    if not AUDIENCIA_IAP:
        return USUARIO_LOCAL
    token = request.headers.get("x-goog-iap-jwt-assertion")
    if not token:
        raise HTTPException(status_code=401, detail="Falta la identidad de IAP.")
    from google.auth.transport import requests as transporte
    from google.oauth2 import id_token

    try:
        datos = id_token.verify_token(token, transporte.Request(), audience=AUDIENCIA_IAP, certs_url=CERTIFICADOS_IAP)
    except ValueError:
        raise HTTPException(status_code=401, detail="La identidad de IAP no es válida.") from None
    return datos["email"]
