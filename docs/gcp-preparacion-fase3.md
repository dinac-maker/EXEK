# Preparación de GCP para la fase 3 (Consola Exek)

Para la persona con permisos de administración en GCP. Toma unos 30 minutos. Se hace en **Cloud Shell** (consola de GCP → ícono **>_**), con el proyecto `exekai` seleccionado.

| Pieza | Para qué |
|---|---|
| Grupo `consola@exek.co` | Quiénes entran a la consola (todos con acceso total) |
| Dataset `exekai.exek_registro` | El registro: clientes, usuarios, roles, etiquetas, componentes, versiones e historial |
| Bucket `exekai-paquetes` | Paquetes de cada cliente: uno por commit y el publicado |
| Cuenta `consola-exek` | Con la que corre la consola |
| Cuenta `eco-districash` | Con la que ECO lee los datos de Districash (una cuenta por cliente) |
| Identity-Aware Proxy (IAP) | Que solo el grupo pueda abrir la consola |
| Llave de GitHub en Secret Manager | Que la consola cree la solicitud de cambio con la carpeta de un cliente nuevo |

Pega primero este bloque. Si cierras Cloud Shell, vuelve a pegarlo.

```bash
EXEKAI_ID=exekai
NUM=$(gcloud projects describe "$EXEKAI_ID" --format 'value(projectNumber)')
BUCKET=exekai-paquetes
GRUPO=consola@exek.co
CONSOLA_SA="consola-exek@${EXEKAI_ID}.iam.gserviceaccount.com"
ECO_SA="eco-prueba@${EXEKAI_ID}.iam.gserviceaccount.com"
GH_SA="github-validacion@${EXEKAI_ID}.iam.gserviceaccount.com"
gcloud config set project "$EXEKAI_ID"

# Dar acceso a un dataset. (El comando "bq add-iam-policy-binding" no funciona sobre
# datasets en estos proyectos: responde "This feature requires allowlisting".)
# Uso: dar_acceso <proyecto:dataset> <READER|WRITER> <correo>
dar_acceso() {
  bq show --format=prettyjson "$1"     | jq --arg r "$2" --arg e "$3" '{access: ((.access + [{role: $r, userByEmail: $e}]) | unique)}' > /tmp/acceso.json     && bq update --source /tmp/acceso.json "$1"
}
```

## 1. Crear el grupo (Google Workspace, no en Cloud Shell)

1. Entra a https://groups.google.com con tu cuenta de Exek → **Crear grupo**.
2. Nombre: `Consola Exek`; correo: `consola@exek.co`.
3. Agrega los dos correos autorizados como miembros.

Para dar o quitar acceso a la consola más adelante, solo se cambian los miembros del grupo.

## 2. Activar los servicios

```bash
gcloud services enable iap.googleapis.com storage.googleapis.com iam.googleapis.com \
  cloudresourcemanager.googleapis.com secretmanager.googleapis.com --project "$EXEKAI_ID"
```

## 3. Registro en BigQuery

```bash
bq --location=US mk --dataset --description "Registro de la Consola Exek (I-NA)" "$EXEKAI_ID:exek_registro"
```

Las tablas las crea la consola la primera vez que arranca.

## 4. Bucket de paquetes

```bash
gcloud storage buckets create "gs://$BUCKET" --location us-central1 \
  --uniform-bucket-level-access --public-access-prevention --project "$EXEKAI_ID"
```

Si el nombre `exekai-paquetes` ya existe en GCP (los nombres de bucket son únicos en todo el mundo), usa otro, por ejemplo `exekai-paquetes-clientes`, y avísame.

## 5. Cuenta de la consola y permisos

```bash
gcloud iam service-accounts create consola-exek --display-name "Consola Exek" --project "$EXEKAI_ID"

# Leer y escribir el registro, y ejecutar consultas
dar_acceso "$EXEKAI_ID:exek_registro" WRITER "$CONSOLA_SA"
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$CONSOLA_SA" --role roles/bigquery.jobUser

# Leer los paquetes por commit y escribir el paquete publicado
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$CONSOLA_SA" --role roles/storage.objectAdmin
```

## 6. Permisos de ECO y de GitHub sobre las piezas nuevas

```bash
# ECO lee el registro y el paquete publicado
dar_acceso "$EXEKAI_ID:exek_registro" READER "$ECO_SA"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$ECO_SA" --role roles/storage.objectViewer

# GitHub guarda el paquete de cada commit que llega a main
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$GH_SA" --role roles/storage.objectCreator
```

## 7. Cuenta de ECO para Districash (primer cliente)

Cada cliente tiene su propia cuenta de ECO, con lectura solo sobre su dataset. ECO la "toma prestada" para consultar los datos de ese cliente y de ningún otro.

```bash
gcloud iam service-accounts create eco-districash --display-name "ECO Districash" --project "$EXEKAI_ID"
CLIENTE_SA="eco-districash@${EXEKAI_ID}.iam.gserviceaccount.com"

# Ejecutar consultas (se cobran a exekai) y leer solo el dataset de Districash
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$CLIENTE_SA" --role roles/bigquery.jobUser
dar_acceso "exek-produccion:NewtonAgentSpace" READER "$CLIENTE_SA"

# ECO puede actuar como esta cuenta
gcloud iam service-accounts add-iam-policy-binding "$CLIENTE_SA" --project "$EXEKAI_ID" \
  --member "serviceAccount:$ECO_SA" --role roles/iam.serviceAccountTokenCreator
```

Si `dar_acceso` da error, da el permiso en pantalla: BigQuery → dataset → **Compartir** → **Administrar permisos** → **Agregar principal** (Visualizador de datos de BigQuery para leer; Editor de datos de BigQuery para escribir).

Para los clientes siguientes, el alta en la consola muestra estos mismos cuatro comandos (crear la cuenta, permiso de consultas, lectura del dataset del cliente y permiso para que ECO actúe como ella) con los datos del cliente, y un botón **Verificar acceso** que revisa todo. La consola no crea cuentas de servicio por su cuenta: así no necesita permisos de administración sobre `exekai`.

## 8. Acceso del grupo con IAP

```bash
# El grupo puede pasar por IAP
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "group:$GRUPO" --role roles/iap.httpsResourceAccessor

# IAP puede llamar a los servicios de Cloud Run del proyecto
gcloud beta services identity create --service iap.googleapis.com --project "$EXEKAI_ID"
gcloud projects add-iam-policy-binding "$EXEKAI_ID" \
  --member "serviceAccount:service-${NUM}@gcp-sa-iap.iam.gserviceaccount.com" --role roles/run.invoker
```

IAP se enciende sobre el servicio `consola-exek` cuando se despliegue por primera vez; ese comando va en la acción de despliegue.

## 9. Llave de GitHub para crear solicitudes de cambio

La consola crea una solicitud de cambio con la carpeta de cada cliente nuevo. Para eso necesita una llave de GitHub con permisos solo sobre `dinac-maker/EXEK`.

1. En GitHub: foto de perfil → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Nombre: `consola-exek`; vencimiento: 1 año; **Repository access**: *Only select repositories* → `dinac-maker/EXEK`.
3. **Permissions**: *Contents* → **Read and write**; *Pull requests* → **Read and write**. Nada más.
4. Copia la llave y guárdala en Secret Manager, en pantalla (no la pegues en ningún otro lugar):
   1. En la consola de GCP, con `exekai` seleccionado, abre **Secret Manager** → **Crear secreto**.
   2. **Nombre:** `github-consola-exek`. **Valor del secreto:** pega la llave, sin espacios ni saltos de línea al final.
   3. Pulsa **Crear secreto**.
5. En Cloud Shell, da permiso a la consola para leerla y comprueba que quedó una versión `enabled`:

```bash
gcloud secrets add-iam-policy-binding github-consola-exek --project "$EXEKAI_ID" \
  --member "serviceAccount:$CONSOLA_SA" --role roles/secretmanager.secretAccessor
gcloud secrets versions list github-consola-exek --project "$EXEKAI_ID"
```

Cuando venza la llave (o si se guardó mal), en Secret Manager abre `github-consola-exek` → **Nueva versión** y pega la llave nueva; la última versión queda como la vigente.

## 10. Permisos de despliegue de la consola

```bash
gcloud iam service-accounts add-iam-policy-binding "$CONSOLA_SA" --project "$EXEKAI_ID" \
  --member "serviceAccount:$GH_SA" --role roles/iam.serviceAccountUser
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$GH_SA" --role roles/iap.admin
```

## 11. Comprobar

```bash
bq show --format=prettyjson "$EXEKAI_ID:exek_registro" | grep -E '"location"|consola-exek|eco-prueba'
bq show --format=prettyjson "exek-produccion:NewtonAgentSpace" | grep eco-districash
gcloud secrets get-iam-policy github-consola-exek --project "$EXEKAI_ID" | grep consola-exek
gcloud projects get-iam-policy "$EXEKAI_ID" --format json | grep gcp-sa-iap
gcloud storage buckets describe "gs://$BUCKET" --format 'value(location)'
gcloud iam service-accounts list --project "$EXEKAI_ID" --format 'value(email)' | grep -E 'consola-exek|eco-districash'
gcloud secrets list --project "$EXEKAI_ID" --format 'value(name)' | grep github-consola-exek
```

Deberías ver: el dataset en `US` con las dos cuentas, el bucket en `US-CENTRAL1`, las dos cuentas nuevas y el secreto.

## 12. Avisar al equipo

Envía: el nombre final del bucket, si algún comando dio error (con el mensaje) y la confirmación de que el grupo `consola@exek.co` existe con sus dos miembros.

**Estado (23/10/2026):** guía corrida. Los permisos sobre datasets, el del secreto y el del agente de IAP se completaron después desde el computador de Dina Silva y quedaron verificados.
