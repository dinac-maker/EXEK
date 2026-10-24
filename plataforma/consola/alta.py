"""Alta de un cliente nuevo: lo automático y lo guiado (decisión del 23/10/2026).

Automático: registro (lo hace el servicio del registro), solicitud de cambio en GitHub
con la carpeta del cliente y espacio de paquetes (en Cloud Storage no hay que crear nada:
la carpeta <cliente>/ aparece con el primer paquete).

Guiado: crear la cuenta de ECO del cliente y darle lectura sobre su dataset. La consola
muestra los comandos y "Verificar acceso" comprueba que quedaron bien.
"""
from __future__ import annotations

import base64
import urllib.error

import yaml

from consola import github

PROYECTO_ECO = "exekai"
CUENTA_ECO_PLATAFORMA = f"eco-prueba@{PROYECTO_ECO}.iam.gserviceaccount.com"
CUENTA_CONSOLA = f"consola-exek@{PROYECTO_ECO}.iam.gserviceaccount.com"


# ---- pasos guiados ------------------------------------------------------------------

def comandos_guiados(cliente: dict) -> list[tuple[str, str]]:
    """(explicación, comando) para correr en Cloud Shell."""
    cid = cliente["cliente_id"]
    sa = cliente["cuenta_eco"]
    ds = f"{cliente['proyecto_datos']}:{cliente['dataset']}"
    return [
        ("Crear la cuenta de ECO del cliente (si ya existe, no hace nada)",
         f"gcloud iam service-accounts describe {sa} --project {PROYECTO_ECO} >/dev/null 2>&1 || "
         f'gcloud iam service-accounts create eco-{cid} --display-name "ECO {cliente["nombre"]}" --project {PROYECTO_ECO}'),
        ("Permitirle ejecutar consultas (se cobran a exekai)",
         f"gcloud projects add-iam-policy-binding {PROYECTO_ECO} --member serviceAccount:{sa} --role roles/bigquery.jobUser"),
        ("Darle lectura solo sobre el dataset del cliente (función dar_acceso de docs/gcp-preparacion-fase3.md)",
         f"dar_acceso {ds} READER {sa}"),
        ("Permitir que ECO actúe como esa cuenta",
         f"gcloud iam service-accounts add-iam-policy-binding {sa} --project {PROYECTO_ECO} "
         f"--member serviceAccount:{CUENTA_ECO_PLATAFORMA} --role roles/iam.serviceAccountTokenCreator"),
        ("Permitir que la consola verifique el acceso",
         f"gcloud iam service-accounts add-iam-policy-binding {sa} --project {PROYECTO_ECO} "
         f"--member serviceAccount:{CUENTA_CONSOLA} --role roles/iam.serviceAccountTokenCreator"),
    ]


def verificar_acceso(cliente: dict) -> tuple[bool, str]:
    """Actúa como la cuenta de ECO del cliente y prueba leer su dataset sin traer datos."""
    import google.auth
    from google.auth import impersonated_credentials
    from google.cloud import bigquery

    try:
        propias, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        prestadas = impersonated_credentials.Credentials(
            source_credentials=propias, target_principal=cliente["cuenta_eco"],
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=300)
        bq = bigquery.Client(project=PROYECTO_ECO, credentials=prestadas)
        ds = f"{cliente['proyecto_datos']}.{cliente['dataset']}"
        tablas = list(bq.list_tables(ds, max_results=1))
        if not tablas:
            return False, f"La cuenta entra al dataset {ds}, pero el dataset no tiene tablas."
        t = tablas[0]
        bq.query(f"SELECT * FROM `{t.project}.{t.dataset_id}.{t.table_id}` LIMIT 1",
                 job_config=bigquery.QueryJobConfig(dry_run=True)).result()
        return True, f"La cuenta {cliente['cuenta_eco']} puede consultar {ds}."
    except Exception as e:  # noqa: BLE001 - se le explica a la persona
        texto = str(e)
        if "iam.serviceAccounts.getAccessToken" in texto or "PERMISSION_DENIED" in texto and "iamcredentials" in texto:
            return False, "La consola no puede actuar como la cuenta del cliente: falta el último comando (o la cuenta no existe)."
        if "Access Denied" in texto or "403" in texto:
            return False, "La cuenta existe pero no puede leer el dataset o ejecutar consultas: revisa los comandos 2 y 3."
        if "Not found" in texto or "404" in texto:
            return False, "No se encontró el dataset o la cuenta: revisa el proyecto, el dataset y el comando 1."
        return False, f"No se pudo verificar: {texto[:300]}"


# ---- solicitud de cambio en GitHub --------------------------------------------------

def archivos_iniciales(cliente: dict) -> dict[str, str]:
    """Carpeta mínima del cliente en el repositorio: valida sin componentes."""
    cid = cliente["cliente_id"]
    manifiesto = {
        "cliente_id": cid,
        "nombre": cliente["nombre"],
        "gcp": {"proyecto_datos": cliente["proyecto_datos"], "proyecto_consultas": PROYECTO_ECO},
        "zona_horaria": "America/Bogota",
        "moneda": "COP",
        "eco": {
            "modelo_por_defecto": "claude-sonnet-5-5",
            "limite_bytes_por_consulta": 2000000000,
            "instrucciones_cliente": f"{cliente['nombre']}. Responde en español, con cifras en pesos colombianos "
                                     "sin decimales y fechas en formato día/mes/año.\n",
        },
    }
    encabezado = ("# Manifiesto técnico del cliente (creado por la Consola Exek).\n"
                  "# Usuarios, roles, etiquetas, visibilidad y programaciones se administran en la consola.\n")
    leeme = (f"# {cliente['nombre']}\n\nAlmacén de componentes creado desde la Consola Exek.\n\n"
             f"- Datos: `{cliente['proyecto_datos']}.{cliente['dataset']}`\n"
             f"- Cuenta de ECO: `{cliente['cuenta_eco']}`\n\n"
             "Siguiente paso: declarar las tablas en `fuentes/` y crear componentes con "
             "`python herramientas/nuevo.py " + cid + " skill <id>`.\n")
    return {
        f"clientes/{cid}/exek.yaml": encabezado + yaml.safe_dump(manifiesto, allow_unicode=True, sort_keys=False),
        f"clientes/{cid}/LEEME.md": leeme,
    }


def crear_solicitud(cliente: dict, quien: str) -> str:
    """Crea la rama alta/<cliente>, sube la carpeta y abre la solicitud de cambio. Devuelve su enlace."""
    llave = github.llave()
    cid = cliente["cliente_id"]
    rama = f"alta/{cid}"
    base = github.llamar("GET", "/git/ref/heads/main", llave)["object"]["sha"]
    try:
        github.llamar("POST", "/git/refs", llave, {"ref": f"refs/heads/{rama}", "sha": base})
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422: la rama ya existe (un intento anterior)
            raise
    for ruta, contenido in archivos_iniciales(cliente).items():
        cuerpo = {"message": f"Alta de {cliente['nombre']}: {ruta.split('/')[-1]}", "branch": rama,
                  "content": base64.b64encode(contenido.encode()).decode()}
        try:
            cuerpo["sha"] = github.llamar("GET", f"/contents/{ruta}?ref={rama}", llave)["sha"]
        except urllib.error.HTTPError:
            pass
        github.llamar("PUT", f"/contents/{ruta}", llave, cuerpo)
    existentes = github.llamar("GET", f"/pulls?head={github.REPOSITORIO.split('/')[0]}:{rama}&state=open", llave)
    if existentes:
        return existentes[0]["html_url"]
    pr = github.llamar("POST", "/pulls", llave, {
        "title": f"Alta del cliente {cliente['nombre']}", "head": rama, "base": "main",
        "body": (f"Carpeta inicial de **{cliente['nombre']}**, creada desde la Consola Exek por {quien}.\n\n"
                 f"- Datos: `{cliente['proyecto_datos']}.{cliente['dataset']}`\n"
                 f"- Dominios: {', '.join(cliente['dominios'])}\n"
                 f"- Cuenta de ECO: `{cliente['cuenta_eco']}`\n")})
    return pr["html_url"]
