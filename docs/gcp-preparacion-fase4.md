# Preparación de GCP para la fase 4 (programaciones, ejecuciones y costos)

Tiene tres partes, que pueden hacer personas distintas:

| Parte | Quién | Tiempo |
|---|---|---|
| 1. Reloj y cuenta de correo (Cloud Shell) | Administración de GCP (`exekai`) | 15 minutos |
| 2. Buzón de alertas y permiso de envío | Administración de Google Workspace de Exek | 10 minutos |
| 3. Exportación de la facturación a BigQuery | Administración de la cuenta de facturación de GCP | 10 minutos |

| Pieza | Para qué |
|---|---|
| Cuenta `reloj-exek` | Con la que Cloud Scheduler despierta a ECO cada 15 minutos |
| Tarea de Cloud Scheduler `reloj-programaciones` | El reloj: llama a ECO para que corra las programaciones pendientes |
| Cuenta `correo-exek` | Con la que ECO envía las alertas desde `alertas@exek.co` (sin llaves) |
| Buzón `alertas@exek.co` | Remitente de las alertas |
| Dataset `exekai.facturacion` | Donde Google deja el detalle de lo que cobra, para cuadrar los costos de cada cliente |

## Parte 1 · Cloud Shell (proyecto `exekai`)

Pega primero este bloque (incluye la función `dar_acceso` de las guías anteriores):

```bash
EXEKAI_ID=exekai
REGION=us-central1
ECO_SA="eco-prueba@${EXEKAI_ID}.iam.gserviceaccount.com"
CONSOLA_SA="consola-exek@${EXEKAI_ID}.iam.gserviceaccount.com"
RELOJ_SA="reloj-exek@${EXEKAI_ID}.iam.gserviceaccount.com"
CORREO_SA="correo-exek@${EXEKAI_ID}.iam.gserviceaccount.com"
gcloud config set project "$EXEKAI_ID"

# Uso: dar_acceso <proyecto:dataset> <READER|WRITER> <correo>
dar_acceso() {
  bq show --format=prettyjson "$1" \
    | jq --arg r "$2" --arg e "$3" '{access: ((.access + [{role: $r, userByEmail: $e}]) | unique)}' > /tmp/acceso.json \
    && bq update --source /tmp/acceso.json "$1"
}
```

### 1.1 Activar los servicios

```bash
gcloud services enable cloudscheduler.googleapis.com gmail.googleapis.com --project "$EXEKAI_ID"
```

### 1.2 Cuenta del reloj

```bash
gcloud iam service-accounts describe "$RELOJ_SA" --project "$EXEKAI_ID" >/dev/null 2>&1 || \
  gcloud iam service-accounts create reloj-exek --display-name "Reloj de programaciones" --project "$EXEKAI_ID"

# El reloj puede llamar al servicio eco (solo a ese)
gcloud run services add-iam-policy-binding eco --region "$REGION" --project "$EXEKAI_ID" \
  --member "serviceAccount:$RELOJ_SA" --role roles/run.invoker

# La consola también llama a eco para el botón "Ejecutar ahora"
gcloud run services add-iam-policy-binding eco --region "$REGION" --project "$EXEKAI_ID" \
  --member "serviceAccount:$CONSOLA_SA" --role roles/run.invoker
```

Si ya corriste esta parte antes de que se agregara el permiso de la consola, corre solo el último comando.

### 1.3 El reloj (queda en pausa hasta desplegar la fase 4)

```bash
ECO_URL=$(gcloud run services describe eco --region "$REGION" --project "$EXEKAI_ID" --format 'value(status.url)')

gcloud scheduler jobs create http reloj-programaciones --location "$REGION" --project "$EXEKAI_ID" \
  --schedule "*/15 * * * *" --time-zone "America/Bogota" \
  --uri "$ECO_URL/programaciones/ejecutar-pendientes" --http-method POST \
  --oidc-service-account-email "$RELOJ_SA" --oidc-token-audience "$ECO_URL" \
  --attempt-deadline 30m \
  --description "Cada 15 minutos: ECO corre las programaciones pendientes de todos los clientes"

gcloud scheduler jobs pause reloj-programaciones --location "$REGION" --project "$EXEKAI_ID"
```

Queda en pausa porque ECO todavía no tiene esa dirección; se activa al final de la fase 4.

### 1.4 Cuenta de correo (sin llaves)

```bash
gcloud iam service-accounts describe "$CORREO_SA" --project "$EXEKAI_ID" >/dev/null 2>&1 || \
  gcloud iam service-accounts create correo-exek --display-name "Correo de alertas" --project "$EXEKAI_ID"

# ECO firma con esta cuenta para enviar correos, sin descargar llaves
gcloud iam service-accounts add-iam-policy-binding "$CORREO_SA" --project "$EXEKAI_ID" \
  --member "serviceAccount:$ECO_SA" --role roles/iam.serviceAccountTokenCreator

# Número que necesita la parte 2 (cópialo)
gcloud iam service-accounts describe "$CORREO_SA" --project "$EXEKAI_ID" --format 'value(oauth2ClientId)'
```

### 1.5 Dataset de facturación (antes de la parte 3)

```bash
bq --location=US mk --dataset --description "Exportación de la facturación de GCP (costos por cliente)" "$EXEKAI_ID:facturacion"
dar_acceso "$EXEKAI_ID:facturacion" READER "$CONSOLA_SA"
```

### 1.6 Comprobar

```bash
gcloud scheduler jobs describe reloj-programaciones --location "$REGION" --project "$EXEKAI_ID" --format 'value(state,schedule,timeZone)'
gcloud run services get-iam-policy eco --region "$REGION" --project "$EXEKAI_ID" | grep reloj-exek
gcloud iam service-accounts get-iam-policy "$CORREO_SA" --project "$EXEKAI_ID" | grep eco-prueba
bq show --format=prettyjson "$EXEKAI_ID:facturacion" | grep -E '"location"|consola-exek'
```

Deberías ver: el reloj en `PAUSED` con `*/15 * * * *` y `America/Bogota`, `reloj-exek` con permiso sobre `eco`, `eco-prueba` con permiso sobre la cuenta de correo, y el dataset `facturacion` en `US` con `consola-exek`.

## Parte 2 · Google Workspace (administración de Exek)

1. **Buzón de alertas.** En https://admin.google.com → **Directorio** → **Usuarios** → **Agregar usuario**: `alertas@exek.co` (nombre: "Alertas Exek"). Necesita licencia de Gmail. Si prefieren otro remitente, avísenme el correo.
2. **Permiso de envío para la cuenta de correo.** En https://admin.google.com → **Seguridad** → **Acceso y control de datos** → **Controles de API** → **Delegación de todo el dominio** → **Agregar nuevo**:
   - **ID de cliente:** el número que imprimió el paso 1.4.
   - **Permisos de OAuth:** `https://www.googleapis.com/auth/gmail.send`
   - Pulsa **Autorizar**.

Este permiso solo deja **enviar** correos a nombre de usuarios de Exek; no permite leer buzones. La plataforma solo lo usa con `alertas@exek.co`.

## Parte 3 · Exportación de la facturación (administración de facturación)

1. En la consola de GCP abre **Facturación** y elige la cuenta de facturación de `exekai`.
2. Menú izquierdo → **Exportación de facturación** → pestaña **Exportación de BigQuery**.
3. **Datos de costo de uso estándar** → **Editar configuración**: proyecto `exekai`, dataset `facturacion` → **Guardar**.
4. **Datos de costo de uso detallado** → **Editar configuración**: proyecto `exekai`, dataset `facturacion` → **Guardar**.

Google empieza a llenar las tablas en unas horas; los datos de días anteriores pueden tardar hasta unos días en aparecer.

## Avisar al equipo

Envía: el número del paso 1.4 (si la parte 2 la hace otra persona), confirmación de que `alertas@exek.co` existe y de la delegación, confirmación de la exportación de facturación, y cualquier error (con el mensaje).
