# Preparación de GCP para la fase 2 (ECO de prueba)

Para la persona con permisos de administración en GCP. Toma unos 30 minutos.

| Proyecto | Para qué |
|---|---|
| **EXEKAI** | Donde corre ECO: Vertex AI (Claude), Cloud Run y las consultas que hace ECO |
| `exek-produccion` | Donde están los datos. ECO **solo lee**, no modifica nada |

Reemplaza `EXEKAI_ID` por el **ID** del proyecto EXEKAI (el ID va en minúsculas; se ve en la consola de GCP, junto al nombre del proyecto).

```bash
EXEKAI_ID=exekai            # reemplazar por el ID real
DATOS=exek-produccion
DATASET=NewtonAgentSpace
REPO=dinac-maker/EXEK

# Dar acceso a un dataset. (El comando "bq add-iam-policy-binding" no funciona sobre
# datasets en estos proyectos: responde "This feature requires allowlisting".)
# Uso: dar_acceso <proyecto:dataset> <READER|WRITER> <correo>
dar_acceso() {
  bq show --format=prettyjson "$1"     | jq --arg r "$2" --arg e "$3" '{access: ((.access + [{role: $r, userByEmail: $e}]) | unique)}' > /tmp/acceso.json     && bq update --source /tmp/acceso.json "$1"
}
```

## 1. Activar los servicios en EXEKAI

```bash
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com run.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com --project "$EXEKAI_ID"
```

## 2. Habilitar los modelos Claude en Vertex AI

En la consola de GCP, con el proyecto EXEKAI seleccionado: **Vertex AI → Model Garden**, busca cada modelo, ábrelo y pulsa **Habilitar** (acepta los términos de Anthropic):

- Claude Sonnet 5.5 (modelo por defecto de ECO)
- Claude Opus 5.5
- Claude Haiku 5.5

El consumo se cobra en la cuenta de facturación del proyecto EXEKAI.

## 3. Cuenta de servicio de ECO

```bash
gcloud iam service-accounts create eco-prueba --display-name "ECO prueba" --project "$EXEKAI_ID"
ECO_SA="eco-prueba@${EXEKAI_ID}.iam.gserviceaccount.com"

# En EXEKAI: usar Claude y ejecutar consultas
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$ECO_SA" --role roles/aiplatform.user
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$ECO_SA" --role roles/bigquery.jobUser

# En exek-produccion: solo lectura del dataset de Districash
dar_acceso "$DATOS:$DATASET" READER "$ECO_SA"
```

## 4. Conexión de GitHub con GCP, sin llaves (Workload Identity Federation)

Permite que la validación automática revise los SQL en BigQuery.

```bash
gcloud iam workload-identity-pools create github --location global --display-name "GitHub" --project "$EXEKAI_ID"

gcloud iam workload-identity-pools providers create-oidc exek --location global \
  --workload-identity-pool github --display-name "Repositorio EXEK" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository == '$REPO'" --project "$EXEKAI_ID"

gcloud iam service-accounts create github-validacion --display-name "GitHub validación" --project "$EXEKAI_ID"
GH_SA="github-validacion@${EXEKAI_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$GH_SA" --role roles/bigquery.jobUser
dar_acceso "$DATOS:$DATASET" READER "$GH_SA"

NUM=$(gcloud projects describe "$EXEKAI_ID" --format 'value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$GH_SA" --project "$EXEKAI_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$NUM/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

echo "GCP_WIF_PROVIDER = projects/$NUM/locations/global/workloadIdentityPools/github/providers/exek"
echo "GCP_SERVICE_ACCOUNT = $GH_SA"
```

Copia los dos valores que imprime el último comando en GitHub: **Settings → Secrets and variables → Actions → Variables → New repository variable**.

## 5. Despliegue de ECO en Cloud Run

Permite que la acción "Desplegar ECO de prueba" de GitHub suba la imagen y despliegue el servicio.

```bash
gcloud artifacts repositories create eco --repository-format docker --location us-central1 --project "$EXEKAI_ID"

gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$GH_SA" --role roles/run.admin
gcloud projects add-iam-policy-binding "$EXEKAI_ID" --member "serviceAccount:$GH_SA" --role roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding "$ECO_SA" --project "$EXEKAI_ID"   --member "serviceAccount:$GH_SA" --role roles/iam.serviceAccountUser
```

Para poder llamar al servicio (no es público), cada persona que lo pruebe necesita el rol **Invocador de Cloud Run**:

```bash
gcloud run services add-iam-policy-binding eco-districash --region us-central1 --project "$EXEKAI_ID"   --member "user:CORREO_DE_LA_PERSONA" --role roles/run.invoker
```

## 6. Avisar al equipo

Con esto listo, envía:

- el ID real del proyecto EXEKAI;
- confirmación de que los tres modelos Claude quedaron habilitados;
- confirmación de que las variables quedaron en GitHub.

En ese momento se actualiza `proyecto_consultas` en `clientes/districash/exek.yaml` para que las consultas de ECO se cobren a EXEKAI.

**Estado (22/10/2026):** pasos 1 a 5 hechos; ECO usa la cuenta `eco-prueba` y está desplegado en Cloud Run (`eco-districash`, `us-central1`).
