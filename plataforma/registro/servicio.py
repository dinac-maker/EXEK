"""Reglas del registro de la Consola Exek.

Todo cambio pasa por aquí: se valida, se guarda y queda en el historial con quién lo
hizo. Los mensajes de error son los que ve la persona de Exek en la consola.

Estados de una versión (se deducen, no se guardan):
- en_produccion: es la versión publicada de un componente activo.
- en_prueba: es más nueva que la publicada (o el componente aún no tiene publicada).
- anterior: es más vieja que la publicada.
"""
from __future__ import annotations

import json
import re
import unicodedata

from registro.almacen import Almacen, Conflicto, Duplicado, ahora

PROYECTO_ECO = "exekai"
TIPOS_COMPONENTE = ("skill", "agente", "artefacto", "plugin")
SISTEMA_GITHUB = "GitHub"

PATRON_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")
PATRON_DOMINIO = re.compile(r"^(?=.{4,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")
PATRON_PROYECTO = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
PATRON_DATASET = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
PATRON_CORREO = re.compile(r"^[^@\s]+@([^@\s]+)$")
PATRON_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class ErrorRegistro(Exception):
    """Cambio no permitido; el mensaje se muestra tal cual en la consola."""


def identificador(nombre: str) -> str:
    """'Producción y Consumos' -> 'produccion-y-consumos'."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")[:63]


def tupla_version(numero: str) -> tuple[int, ...]:
    return tuple(int(x) for x in numero.split("."))


def _texto(valor) -> str | None:
    return json.dumps(valor, ensure_ascii=False, default=str, sort_keys=True) if valor is not None else None


class Registro:
    def __init__(self, almacen: Almacen):
        self.almacen = almacen

    # ---- utilidades ---------------------------------------------------------------

    def _anotar(self, quien, tipo, accion, detalle, cliente_id=None, objeto_id=None, antes=None, despues=None):
        self.almacen.insertar("historial", {
            "fecha": ahora(), "cliente_id": cliente_id, "quien": quien, "tipo": tipo, "accion": accion,
            "objeto_id": objeto_id, "detalle": detalle, "antes": _texto(antes), "despues": _texto(despues),
        })

    def _auditoria(self, quien: str) -> dict:
        t = ahora()
        return {"creado": t, "creado_por": quien, "actualizado": t, "actualizado_por": quien, "revision": 1}

    def _cambio(self, quien: str) -> dict:
        return {"actualizado": ahora(), "actualizado_por": quien}

    def _insertar(self, tabla: str, fila: dict, ya_existe: str) -> dict:
        try:
            return self.almacen.insertar(tabla, fila)
        except Duplicado:
            raise ErrorRegistro(ya_existe) from None

    def _actualizar(self, tabla: str, clave: dict, cambios: dict, revision: int) -> dict:
        try:
            return self.almacen.actualizar(tabla, clave, cambios, revision)
        except Conflicto:
            raise ErrorRegistro("Alguien cambió este dato mientras lo editabas. Recarga la página y vuelve a intentarlo.") from None

    def cliente(self, cliente_id: str) -> dict:
        c = self.almacen.obtener("clientes", cliente_id=cliente_id)
        if c is None:
            raise ErrorRegistro(f"No existe el cliente '{cliente_id}'.")
        return c

    # ---- clientes -----------------------------------------------------------------

    def clientes(self) -> list[dict]:
        return self.almacen.listar("clientes")

    def crear_cliente(self, quien: str, nombre: str, dominios: list[str], proyecto_datos: str,
                      dataset: str, cliente_id: str | None = None) -> dict:
        nombre = (nombre or "").strip()
        if len(nombre) < 2:
            raise ErrorRegistro("Escribe el nombre del cliente.")
        cliente_id = cliente_id or identificador(nombre)[:26].strip("-")
        if not PATRON_ID.match(cliente_id):
            raise ErrorRegistro("El identificador del cliente solo puede tener minúsculas, números y guiones.")
        if len(cliente_id) > 26:  # la cuenta eco-<cliente> no puede pasar de 30 caracteres en GCP
            raise ErrorRegistro("El identificador del cliente puede tener máximo 26 caracteres.")
        dominios = sorted({d.strip().lower() for d in dominios if d and d.strip()})
        if not dominios:
            raise ErrorRegistro("Escribe al menos un dominio de correo del cliente, por ejemplo districash.com.")
        malos = [d for d in dominios if not PATRON_DOMINIO.match(d)]
        if malos:
            raise ErrorRegistro(f"Estos dominios no son válidos: {', '.join(malos)}.")
        proyecto_datos = (proyecto_datos or "").strip()
        if not PATRON_PROYECTO.match(proyecto_datos):
            raise ErrorRegistro("El proyecto de GCP no es válido: son 6 a 30 caracteres en minúsculas, números y guiones.")
        dataset = (dataset or "").strip()
        if not PATRON_DATASET.match(dataset):
            raise ErrorRegistro("El dataset no es válido: solo letras, números y guiones bajos.")
        fila = {
            "cliente_id": cliente_id, "nombre": nombre, "dominios": dominios,
            "proyecto_datos": proyecto_datos, "dataset": dataset,
            "cuenta_eco": f"eco-{cliente_id}@{PROYECTO_ECO}.iam.gserviceaccount.com"[:200],
            "acceso_verificado": False, "estado": "activo", **self._auditoria(quien),
        }
        fila = self._insertar("clientes", fila, f"Ya existe un cliente con el identificador '{cliente_id}'.")
        self._anotar(quien, "cliente", "crear", f"Cliente {nombre} creado", cliente_id, cliente_id, despues=fila)
        return fila

    def actualizar_cliente(self, quien: str, cliente_id: str, revision: int, **cambios) -> dict:
        permitidos = {"nombre", "dominios", "proyecto_datos", "dataset", "estado", "acceso_verificado"}
        if set(cambios) - permitidos:
            raise ErrorRegistro(f"No se pueden cambiar: {', '.join(sorted(set(cambios) - permitidos))}.")
        antes = self.cliente(cliente_id)
        if "dominios" in cambios:
            cambios["dominios"] = sorted({d.strip().lower() for d in cambios["dominios"] if d.strip()})
            if not cambios["dominios"] or any(not PATRON_DOMINIO.match(d) for d in cambios["dominios"]):
                raise ErrorRegistro("Revisa los dominios de correo.")
        if "proyecto_datos" in cambios and not PATRON_PROYECTO.match(cambios["proyecto_datos"]):
            raise ErrorRegistro("El proyecto de GCP no es válido.")
        if "dataset" in cambios and not PATRON_DATASET.match(cambios["dataset"]):
            raise ErrorRegistro("El dataset no es válido.")
        if cambios.get("estado") not in (None, "activo", "inactivo"):
            raise ErrorRegistro("El estado debe ser activo o inactivo.")
        if {"proyecto_datos", "dataset"} & set(cambios):
            cambios["acceso_verificado"] = False  # hay que verificar el acceso de nuevo
        nuevo = self._actualizar("clientes", {"cliente_id": cliente_id}, {**cambios, **self._cambio(quien)}, revision)
        self._anotar(quien, "cliente", "actualizar", f"Cliente {nuevo['nombre']} actualizado", cliente_id, cliente_id,
                     antes={k: antes[k] for k in cambios}, despues={k: nuevo[k] for k in cambios})
        return nuevo

    # ---- etiquetas ----------------------------------------------------------------

    def etiquetas(self, cliente_id: str) -> list[dict]:
        return self.almacen.listar("etiquetas", cliente_id=cliente_id)

    def crear_etiqueta(self, quien: str, cliente_id: str, nombre: str, color: str | None = None) -> dict:
        self.cliente(cliente_id)
        nombre = (nombre or "").strip()
        etiqueta_id = identificador(nombre)
        if not etiqueta_id:
            raise ErrorRegistro("Escribe el nombre de la etiqueta.")
        fila = {"cliente_id": cliente_id, "etiqueta_id": etiqueta_id, "nombre": nombre, "color": color,
                **self._auditoria(quien)}
        fila = self._insertar("etiquetas", fila, f"Ya existe la etiqueta {nombre}.")
        self._anotar(quien, "etiqueta", "crear", f"Etiqueta {nombre} creada", cliente_id, etiqueta_id, despues=fila)
        return fila

    def renombrar_etiqueta(self, quien: str, cliente_id: str, etiqueta_id: str, nombre: str, revision: int,
                           color: str | None = None) -> dict:
        antes = self.almacen.obtener("etiquetas", cliente_id=cliente_id, etiqueta_id=etiqueta_id)
        if antes is None:
            raise ErrorRegistro("Esa etiqueta ya no existe.")
        nombre = (nombre or "").strip()
        if not nombre:
            raise ErrorRegistro("Escribe el nombre de la etiqueta.")
        if any(e["nombre"].lower() == nombre.lower() and e["etiqueta_id"] != etiqueta_id for e in self.etiquetas(cliente_id)):
            raise ErrorRegistro(f"Ya existe la etiqueta {nombre}.")
        nuevo = self._actualizar("etiquetas", {"cliente_id": cliente_id, "etiqueta_id": etiqueta_id},
                                 {"nombre": nombre, "color": color if color is not None else antes["color"], **self._cambio(quien)},
                                 revision)
        self._anotar(quien, "etiqueta", "actualizar", f"Etiqueta {antes['nombre']} ahora se llama {nombre}",
                     cliente_id, etiqueta_id, antes={"nombre": antes["nombre"]}, despues={"nombre": nombre})
        return nuevo

    def eliminar_etiqueta(self, quien: str, cliente_id: str, etiqueta_id: str, revision: int) -> None:
        e = self.almacen.obtener("etiquetas", cliente_id=cliente_id, etiqueta_id=etiqueta_id)
        if e is None:
            raise ErrorRegistro("Esa etiqueta ya no existe.")
        en_roles = [r["nombre"] for r in self.roles(cliente_id) if etiqueta_id in r["etiquetas"]]
        en_comp = [c["nombre"] for c in self.componentes(cliente_id) if etiqueta_id in c["etiquetas"]]
        if en_roles or en_comp:
            usos = ([f"roles: {', '.join(en_roles)}"] if en_roles else []) + ([f"componentes: {', '.join(en_comp)}"] if en_comp else [])
            raise ErrorRegistro(f"La etiqueta {e['nombre']} está en uso ({'; '.join(usos)}). Quítala de ahí antes de eliminarla.")
        try:
            self.almacen.eliminar("etiquetas", {"cliente_id": cliente_id, "etiqueta_id": etiqueta_id}, revision)
        except Conflicto:
            raise ErrorRegistro("Alguien cambió esta etiqueta mientras la editabas. Recarga la página.") from None
        self._anotar(quien, "etiqueta", "eliminar", f"Etiqueta {e['nombre']} eliminada", cliente_id, etiqueta_id, antes=e)

    def _revisar_etiquetas(self, cliente_id: str, etiquetas: list[str]) -> list[str]:
        existentes = {e["etiqueta_id"] for e in self.etiquetas(cliente_id)}
        etiquetas = sorted(set(etiquetas or []))
        faltan = [e for e in etiquetas if e not in existentes]
        if faltan:
            raise ErrorRegistro(f"Estas etiquetas no existen en el cliente: {', '.join(faltan)}.")
        return etiquetas

    # ---- roles --------------------------------------------------------------------

    def roles(self, cliente_id: str) -> list[dict]:
        return self.almacen.listar("roles", cliente_id=cliente_id)

    def crear_rol(self, quien: str, cliente_id: str, nombre: str, etiquetas: list[str],
                  descripcion: str | None = None) -> dict:
        self.cliente(cliente_id)
        nombre = (nombre or "").strip()
        rol_id = identificador(nombre)
        if not rol_id:
            raise ErrorRegistro("Escribe el nombre del rol.")
        fila = {"cliente_id": cliente_id, "rol_id": rol_id, "nombre": nombre, "descripcion": descripcion,
                "etiquetas": self._revisar_etiquetas(cliente_id, etiquetas), **self._auditoria(quien)}
        fila = self._insertar("roles", fila, f"Ya existe el rol {nombre}.")
        self._anotar(quien, "rol", "crear", f"Rol {nombre} creado", cliente_id, rol_id, despues=fila)
        return fila

    def actualizar_rol(self, quien: str, cliente_id: str, rol_id: str, revision: int, *,
                       etiquetas: list[str] | None = None, descripcion: str | None = None) -> dict:
        antes = self.almacen.obtener("roles", cliente_id=cliente_id, rol_id=rol_id)
        if antes is None:
            raise ErrorRegistro("Ese rol ya no existe.")
        cambios = {}
        if etiquetas is not None:
            cambios["etiquetas"] = self._revisar_etiquetas(cliente_id, etiquetas)
        if descripcion is not None:
            cambios["descripcion"] = descripcion
        nuevo = self._actualizar("roles", {"cliente_id": cliente_id, "rol_id": rol_id}, {**cambios, **self._cambio(quien)}, revision)
        self._anotar(quien, "rol", "actualizar", f"Rol {antes['nombre']} actualizado", cliente_id, rol_id,
                     antes={k: antes[k] for k in cambios}, despues={k: nuevo[k] for k in cambios})
        return nuevo

    # ---- usuarios -----------------------------------------------------------------

    def usuarios(self, cliente_id: str) -> list[dict]:
        return self.almacen.listar("usuarios", cliente_id=cliente_id)

    def usuario(self, correo: str) -> dict | None:
        return self.almacen.obtener("usuarios", correo=(correo or "").strip().lower())

    def crear_usuario(self, quien: str, cliente_id: str, correo: str, rol_id: str, nombre: str | None = None) -> dict:
        cliente = self.cliente(cliente_id)
        correo = (correo or "").strip().lower()
        m = PATRON_CORREO.match(correo)
        if not m:
            raise ErrorRegistro("Escribe un correo válido.")
        if m.group(1) not in cliente["dominios"]:
            raise ErrorRegistro(f"El correo debe ser de {' o '.join(cliente['dominios'])}.")
        if self.almacen.obtener("roles", cliente_id=cliente_id, rol_id=rol_id) is None:
            raise ErrorRegistro("Elige un rol del cliente.")
        fila = {"correo": correo, "cliente_id": cliente_id, "nombre": (nombre or "").strip() or None,
                "rol_id": rol_id, "estado": "activo", **self._auditoria(quien)}
        fila = self._insertar("usuarios", fila, f"El correo {correo} ya está registrado.")
        self._anotar(quien, "usuario", "crear", f"Usuario {correo} creado con el rol {rol_id}", cliente_id, correo, despues=fila)
        return fila

    def actualizar_usuario(self, quien: str, correo: str, revision: int, *, rol_id: str | None = None,
                           estado: str | None = None, nombre: str | None = None) -> dict:
        antes = self.usuario(correo)
        if antes is None:
            raise ErrorRegistro("Ese usuario ya no existe.")
        cambios = {}
        if rol_id is not None:
            if self.almacen.obtener("roles", cliente_id=antes["cliente_id"], rol_id=rol_id) is None:
                raise ErrorRegistro("Elige un rol del cliente.")
            cambios["rol_id"] = rol_id
        if estado is not None:
            if estado not in ("activo", "inactivo"):
                raise ErrorRegistro("El estado debe ser activo o inactivo.")
            cambios["estado"] = estado
        if nombre is not None:
            cambios["nombre"] = nombre.strip() or None
        nuevo = self._actualizar("usuarios", {"correo": antes["correo"]}, {**cambios, **self._cambio(quien)}, revision)
        self._anotar(quien, "usuario", "actualizar", f"Usuario {antes['correo']} actualizado", antes["cliente_id"],
                     antes["correo"], antes={k: antes[k] for k in cambios}, despues={k: nuevo[k] for k in cambios})
        return nuevo

    # ---- componentes y versiones --------------------------------------------------

    def componentes(self, cliente_id: str) -> list[dict]:
        return self.almacen.listar("componentes", cliente_id=cliente_id)

    def componente(self, cliente_id: str, componente_id: str) -> dict:
        c = self.almacen.obtener("componentes", cliente_id=cliente_id, componente_id=componente_id)
        if c is None:
            raise ErrorRegistro(f"No existe el componente '{componente_id}'.")
        return c

    @staticmethod
    def _con_estados(comp: dict, vs: list[dict]) -> list[dict]:
        vs = sorted(vs, key=lambda v: tupla_version(v["numero"]), reverse=True)
        prod = comp["version_produccion"] if comp["estado"] == "activo" else None
        for v in vs:
            if prod and v["numero"] == prod:
                v["estado"] = "en_produccion"
            elif not prod or tupla_version(v["numero"]) > tupla_version(prod):
                v["estado"] = "en_prueba" if comp["estado"] == "activo" else "retirada"
            else:
                v["estado"] = "anterior"
        return vs

    def versiones(self, cliente_id: str, componente_id: str) -> list[dict]:
        """Versiones de un componente, de la más nueva a la más vieja, con su estado."""
        comp = self.componente(cliente_id, componente_id)
        return self._con_estados(comp, self.almacen.listar("versiones", cliente_id=cliente_id, componente_id=componente_id))

    def version_en_prueba(self, cliente_id: str, componente_id: str) -> str | None:
        """La versión más nueva que todavía no está publicada, si la hay."""
        for v in self.versiones(cliente_id, componente_id):
            if v["estado"] == "en_prueba":
                return v["numero"]
        return None

    def almacen_completo(self, cliente_id: str) -> list[dict]:
        """Componentes del cliente con sus versiones y su versión en prueba, en dos consultas
        (en BigQuery cada consulta tarda alrededor de un segundo)."""
        todas = self.almacen.listar("versiones", cliente_id=cliente_id)
        salida = []
        for c in self.componentes(cliente_id):
            vs = self._con_estados(c, [v for v in todas if v["componente_id"] == c["componente_id"]])
            salida.append({**c, "versiones": vs,
                           "en_prueba": next((v["numero"] for v in vs if v["estado"] == "en_prueba"), None)})
        return salida

    def registrar_version(self, cliente_id: str, componente_id: str, tipo: str, nombre: str, numero: str,
                          commit: str, notas: str | None = None, autor: str | None = None,
                          paquete_uri: str | None = None, quien: str = SISTEMA_GITHUB) -> dict | None:
        """Registra una versión que llegó a main. Si ya estaba registrada, no hace nada.
        Devuelve la versión nueva o None."""
        self.cliente(cliente_id)
        if tipo not in TIPOS_COMPONENTE:
            raise ErrorRegistro(f"Tipo de componente desconocido: {tipo}.")
        if not PATRON_VERSION.match(numero or ""):
            raise ErrorRegistro(f"Versión no válida: {numero}.")
        comp = self.almacen.obtener("componentes", cliente_id=cliente_id, componente_id=componente_id)
        if comp is None:
            comp = self.almacen.insertar("componentes", {
                "cliente_id": cliente_id, "componente_id": componente_id, "tipo": tipo, "nombre": nombre,
                "etiquetas": [], "visible_portal": False, "version_produccion": None, "estado": "activo",
                **self._auditoria(quien)})
            self._anotar(quien, "componente", "crear", f"Componente {nombre} agregado al almacén", cliente_id,
                         componente_id, despues=comp)
        elif comp["nombre"] != nombre or comp["tipo"] != tipo:
            self.almacen.actualizar("componentes", {"cliente_id": cliente_id, "componente_id": componente_id},
                                    {"nombre": nombre, "tipo": tipo, **self._cambio(quien)}, comp["revision"])
        if self.almacen.obtener("versiones", cliente_id=cliente_id, componente_id=componente_id, numero=numero):
            return None
        v = self.almacen.insertar("versiones", {
            "cliente_id": cliente_id, "componente_id": componente_id, "numero": numero, "commit": commit,
            "notas": notas, "autor": autor, "paquete_uri": paquete_uri, "registrada": ahora(), "registrada_por": quien})
        self._anotar(quien, "version", "registrar", f"Nueva versión en prueba: {nombre} {numero}", cliente_id,
                     componente_id, despues={"numero": numero, "commit": commit})
        return v

    def configurar_componente(self, quien: str, cliente_id: str, componente_id: str, revision: int, *,
                              etiquetas: list[str] | None = None, visible_portal: bool | None = None) -> dict:
        antes = self.componente(cliente_id, componente_id)
        cambios = {}
        if etiquetas is not None:
            cambios["etiquetas"] = self._revisar_etiquetas(cliente_id, etiquetas)
        if visible_portal is not None:
            cambios["visible_portal"] = bool(visible_portal)
        nuevo = self._actualizar("componentes", {"cliente_id": cliente_id, "componente_id": componente_id},
                                 {**cambios, **self._cambio(quien)}, revision)
        self._anotar(quien, "componente", "actualizar", f"Componente {antes['nombre']} actualizado", cliente_id,
                     componente_id, antes={k: antes[k] for k in cambios}, despues={k: nuevo[k] for k in cambios})
        return nuevo

    def publicar(self, quien: str, cliente_id: str, componente_id: str, numero: str, revision: int) -> dict:
        """Pone una versión en producción. Sirve también para volver a una anterior."""
        antes = self.componente(cliente_id, componente_id)
        if self.almacen.obtener("versiones", cliente_id=cliente_id, componente_id=componente_id, numero=numero) is None:
            raise ErrorRegistro(f"La versión {numero} de {antes['nombre']} no está registrada.")
        if antes["estado"] == "activo" and antes["version_produccion"] == numero:
            raise ErrorRegistro(f"La versión {numero} ya está en producción.")
        nuevo = self._actualizar("componentes", {"cliente_id": cliente_id, "componente_id": componente_id},
                                 {"version_produccion": numero, "estado": "activo", **self._cambio(quien)}, revision)
        previa = antes["version_produccion"] if antes["estado"] == "activo" else None
        if previa and tupla_version(numero) < tupla_version(previa):
            detalle = f"{antes['nombre']} volvió a la versión {numero} (estaba en {previa})"
        else:
            detalle = f"Publicada {antes['nombre']} {numero}" + (f" (antes {previa})" if previa else "")
        self._anotar(quien, "componente", "publicar", detalle, cliente_id, componente_id,
                     antes={"version_produccion": previa}, despues={"version_produccion": numero})
        return nuevo

    def retirar(self, quien: str, cliente_id: str, componente_id: str, revision: int) -> dict:
        antes = self.componente(cliente_id, componente_id)
        if antes["estado"] == "retirado":
            raise ErrorRegistro(f"{antes['nombre']} ya está retirado.")
        nuevo = self._actualizar("componentes", {"cliente_id": cliente_id, "componente_id": componente_id},
                                 {"estado": "retirado", **self._cambio(quien)}, revision)
        self._anotar(quien, "componente", "retirar", f"{antes['nombre']} retirado (estaba en {antes['version_produccion']})",
                     cliente_id, componente_id, antes={"estado": "activo"}, despues={"estado": "retirado"})
        return nuevo

    # ---- lo que usa ECO -----------------------------------------------------------

    def publicados(self, cliente_id: str) -> list[dict]:
        """Componentes activos con versión en producción: forman el paquete publicado."""
        return [c for c in self.componentes(cliente_id) if c["estado"] == "activo" and c["version_produccion"]]

    def permitidos_para_rol(self, cliente_id: str, rol_id: str) -> list[dict]:
        """Componentes publicados con al menos una etiqueta del rol (decisión 22/10/2026)."""
        rol = self.almacen.obtener("roles", cliente_id=cliente_id, rol_id=rol_id)
        if rol is None:
            return []
        suyas = set(rol["etiquetas"])
        return [c for c in self.publicados(cliente_id) if suyas & set(c["etiquetas"])]

    def acceso_eco(self, correo: str) -> dict:
        """Lo que ECO necesita para atender a un usuario: su cliente, su rol, los componentes
        que puede usar y todos los publicados (para las dependencias), cada uno con el commit
        de su versión en producción. Si no puede usar ECO, el error explica por qué."""
        u = self.usuario(correo)
        if u is None:
            raise ErrorRegistro("Tu usuario no está registrado para usar ECO. Pide acceso al equipo de Exek.")
        if u["estado"] != "activo":
            raise ErrorRegistro("Tu usuario está inactivo. Pide al equipo de Exek que lo active.")
        cliente = self.cliente(u["cliente_id"])
        if cliente["estado"] != "activo":
            raise ErrorRegistro(f"{cliente['nombre']} está inactivo en la plataforma.")
        rol = self.almacen.obtener("roles", cliente_id=cliente["cliente_id"], rol_id=u["rol_id"])
        suyas = set(rol["etiquetas"]) if rol else set()
        publicados = []
        for c in self.almacen_completo(cliente["cliente_id"]):
            if c["estado"] != "activo" or not c["version_produccion"]:
                continue
            v = next((v for v in c["versiones"] if v["numero"] == c["version_produccion"]), None)
            if v is not None:
                publicados.append({**{k: c[k] for k in ("componente_id", "tipo", "nombre", "etiquetas", "version_produccion")},
                                   "commit": v["commit"]})
        elegidos = [c for c in publicados if suyas & set(c["etiquetas"])]
        return {"usuario": u, "cliente": cliente, "rol": rol, "elegidos": elegidos, "publicados": publicados}

    def permitidos_para_usuario(self, correo: str) -> tuple[dict | None, list[dict]]:
        """(usuario, componentes que puede usar). Sin usuario activo, no hay componentes."""
        u = self.usuario(correo)
        if u is None or u["estado"] != "activo":
            return u, []
        return u, self.permitidos_para_rol(u["cliente_id"], u["rol_id"])

    # ---- historial ----------------------------------------------------------------

    def historial(self, cliente_id: str | None = None) -> list[dict]:
        filas = self.almacen.listar("historial", **({"cliente_id": cliente_id} if cliente_id else {}))
        filas.sort(key=lambda h: h["fecha"], reverse=True)
        return filas
