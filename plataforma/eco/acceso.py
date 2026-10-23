"""ECO en modo producción: qué puede usar cada usuario según el registro de la Consola Exek.

Para cada pregunta:
1. Busca al usuario en el registro (exekai.exek_registro): su cliente y su rol.
2. Arma el paquete publicado con los componentes de las etiquetas de su rol, cada uno en
   su versión en producción, desde los paquetes por commit de Cloud Storage.
3. Prepara las credenciales de la cuenta de ECO del cliente (eco-<cliente>), para que las
   consultas solo puedan leer los datos de ese cliente.

Lo que lee del registro se guarda en memoria unos minutos (decisión del 23/10/2026), y
cada paquete publicado se arma una sola vez por combinación de versiones.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from eco.configuracion import PROYECTO_ECO, Cliente, cargar_cliente
from eco.paquete import Paquete, cargar
from registro.almacen import AlmacenBigQuery
from registro.paquetes import BUCKET, PaquetesGCS, armar_publicado
from registro.servicio import ErrorRegistro, Registro

VIGENCIA = int(os.environ.get("ECO_REGISTRO_VIGENCIA", "300"))  # segundos que vale lo leído del registro
CACHE = Path(os.environ.get("ECO_CACHE_PAQUETES", Path(tempfile.gettempdir()) / "eco-publicados"))


class SinAcceso(Exception):
    """El usuario no puede usar ECO; el mensaje se le muestra tal cual."""


@dataclass
class Atencion:
    usuario: str
    cliente: Cliente
    rol: str | None
    paquete: Paquete
    credenciales: object | None
    cuenta_datos: str | None


def actuar_como_cliente() -> bool:
    """En Cloud Run (K_SERVICE) ECO siempre consulta con la cuenta del cliente. En el
    computador del autor solo si ECO_ACTUAR_COMO_CLIENTE=1 (hace falta permiso para actuar
    como esa cuenta)."""
    valor = os.environ.get("ECO_ACTUAR_COMO_CLIENTE")
    return valor == "1" if valor is not None else bool(os.environ.get("K_SERVICE"))


def credenciales_de(cuenta: str):
    import google.auth
    from google.auth import impersonated_credentials

    propias, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return impersonated_credentials.Credentials(
        source_credentials=propias, target_principal=cuenta,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=3600)


class AccesoRegistro:
    def __init__(self, registro: Registro | None = None, paquetes=None):
        self.registro = registro or Registro(AlmacenBigQuery(
            os.environ.get("ECO_REGISTRO_PROYECTO", PROYECTO_ECO), os.environ.get("ECO_REGISTRO_DATASET", "exek_registro")))
        self.paquetes = paquetes or PaquetesGCS(os.environ.get("ECO_BUCKET", BUCKET))
        self._accesos: dict[str, tuple[float, dict]] = {}
        self._paquetes: dict[tuple, Paquete] = {}
        self._candado = threading.Lock()

    def _acceso(self, correo: str) -> dict:
        correo = (correo or "").strip().lower()
        guardado = self._accesos.get(correo)
        if guardado and time.monotonic() - guardado[0] < VIGENCIA:
            return guardado[1]
        try:
            acceso = self.registro.acceso_eco(correo)
        except ErrorRegistro as e:
            raise SinAcceso(str(e)) from None
        self._accesos[correo] = (time.monotonic(), acceso)
        return acceso

    def _paquete(self, cliente_id: str, elegidos: list[dict], publicados: list[dict]) -> Paquete:
        clave = (cliente_id, tuple(sorted((c["componente_id"], c["version_produccion"], c["commit"]) for c in elegidos)),
                 tuple(sorted((c["componente_id"], c["version_produccion"]) for c in publicados)))
        with self._candado:
            if clave not in self._paquetes:
                destino = CACHE / "publicados" / f"{cliente_id}-{abs(hash(clave)):x}"
                armar_publicado(cliente_id, elegidos, publicados, self.paquetes, CACHE / "commits", destino)
                self._paquetes[clave] = cargar(destino)
            return self._paquetes[clave]

    def atender(self, correo: str) -> Atencion:
        a = self._acceso(correo)
        if not a["elegidos"]:
            raise SinAcceso("Tu rol todavía no tiene componentes publicados en ECO. Pide al equipo de Exek que los habilite.")
        cliente = cargar_cliente(a["cliente"]["cliente_id"])
        paquete = self._paquete(cliente.cliente_id, a["elegidos"], a["publicados"])
        cuenta = a["cliente"]["cuenta_eco"] if actuar_como_cliente() else None
        return Atencion(usuario=a["usuario"]["correo"], cliente=cliente, rol=a["usuario"]["rol_id"], paquete=paquete,
                        credenciales=credenciales_de(cuenta) if cuenta else None, cuenta_datos=cuenta)
