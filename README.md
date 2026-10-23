# EXEK · Almacenes de componentes de I-NA

Repositorio del equipo de Exek. Aquí vive el **almacén de componentes de cada cliente**: los skills, agentes, artefactos y plugins que usa ECO, el asistente de IA de I-NA.

Las definiciones completas del diseño están en [`docs/definiciones.md`](docs/definiciones.md).

## Estructura

```
EXEK/
├── docs/                     Definiciones del diseño
├── esquemas/                 Reglas de cada ficha (JSON Schema)
├── plantillas/               Punto de partida por tipo de componente
├── clientes/
│   └── <cliente>/            Almacén de un cliente
│       ├── exek.yaml         Manifiesto técnico del cliente
│       ├── fuentes/          Tablas de BigQuery que leen los componentes
│       ├── skills/<id>/      SKILL.md + componente.yaml + consulta.sql
│       ├── agentes/<id>/     agente.md + componente.yaml
│       ├── artefactos/<id>/  componente.yaml + definición (por ejemplo, tablero.yaml)
│       ├── plugins/<id>/     componente.yaml + conector (solo si los datos no están en BigQuery)
│       └── pruebas/          Preguntas de prueba para ECO
├── herramientas/             Validador, empaquetador y creador de componentes
├── plataforma/eco/           ECO de prueba: motor, consulta segura de BigQuery, registro y pruebas
├── plataforma/registro/      Registro de la Consola Exek en BigQuery (clientes, roles, etiquetas, versiones)
├── plataforma/consola/       Consola Exek: pantallas web para administrar clientes y almacenes
└── .github/workflows/        Validación automática en cada cambio
```

## Reglas del almacén

1. **Cada cliente es distinto.** Cada componente pertenece a un solo cliente. Para reutilizar algo de otro cliente se copia, no se enlaza.
2. **Aquí va qué hace cada componente** (instrucciones, consultas, parámetros). Quién lo usa, cuándo corre y qué versión está publicada se administra en la Consola Exek.
3. Una carpeta por componente, con su `componente.yaml`. El `id` es igual al nombre de la carpeta.
4. **Todo cambio sube la `version`** del componente y explica el cambio en `notas_version`.
5. Toda tabla que use un SQL debe estar declarada en `fuentes/`.
6. Nada de contraseñas ni llaves en el repositorio. Las credenciales de los plugins viven en Secret Manager.

## Herramientas

Requisitos: Python 3.11 o superior.

```bash
pip install -r herramientas/requirements.txt

# Crear un componente nuevo desde la plantilla
python herramientas/nuevo.py districash skill margen-por-linea

# Validar el almacén de un cliente
python herramientas/validar.py clientes/districash

# Validar además los SQL en BigQuery (modo de prueba, sin leer datos)
python herramientas/validar.py clientes/districash --bigquery

# Validar que los componentes cambiados subieron su versión
python herramientas/validar.py clientes/districash --base origin/main

# Armar el paquete del cliente (formato de plugin de Anthropic)
python herramientas/empaquetar.py clientes/districash --salida dist
```

## Validación automática

Cada cambio en `clientes/`, `esquemas/`, `herramientas/` o `plantillas/` dispara la acción **Validar almacenes**, que:

1. valida solo los clientes que cambiaron (o todos, si cambiaron las reglas o las herramientas);
2. en las solicitudes de cambio, exige que los componentes modificados suban su versión;
3. revisa los SQL en BigQuery si el acceso a GCP está configurado (ver abajo);
4. arma el paquete de cada cliente y lo deja como archivo descargable de la ejecución.

### Activar la revisión de SQL en BigQuery

La acción se conecta a GCP con Workload Identity Federation, sin llaves guardadas. Configura en GitHub, en *Settings → Secrets and variables → Actions → Variables*:

| Variable | Valor |
|---|---|
| `GCP_WIF_PROVIDER` | Proveedor de Workload Identity, por ejemplo `projects/123/locations/global/workloadIdentityPools/github/providers/exek` |
| `GCP_SERVICE_ACCOUNT` | Cuenta de servicio con permiso `BigQuery Job User` y lectura de los datasets de los clientes |

Si las variables no están, la acción valida todo lo demás y omite la revisión en BigQuery.

## ECO de prueba (fase 2)

ECO responde preguntas con los skills del cliente y sus tablas de BigQuery, usando el Agent SDK de Claude por Vertex AI (proyecto `exekai`). El estado y las decisiones están en [`docs/definiciones.md`](docs/definiciones.md), secciones 5 y 9.

Requisitos para probarlo en tu computador: Python 3.11 o superior y [Google Cloud SDK](https://cloud.google.com/sdk/docs/install), con tus credenciales:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project exekai
pip install -r plataforma/eco/requirements.txt
```

Desde la carpeta `plataforma/`:

```bash
python -m eco "¿Cuántos clientes perdidos tenemos?"                # una pregunta
python -m eco --detalle "¿Cómo nos fue en ventas el mes pasado?"   # con skills, consultas, tokens y costo
python -m eco                                                      # conversación; escribe "salir" para terminar
python -m eco --modo produccion --usuario comercial.demo@exek.co "..."   # como lo ve un usuario registrado: lo publicado para su rol
python -m eco.pruebas                                              # corre pruebas/casos.yaml y compara cifras con BigQuery
```

Cada respuesta queda en `.eco/ejecuciones.jsonl` (no se sube a Git).

### Probar el ECO desplegado (Cloud Run)

El servicio `eco` (uno solo para todos los clientes) no es público: abrir su dirección en el navegador responde 403. Para probarlo con tu cuenta, abre un túnel y usa la página de pruebas:

```bash
gcloud run services proxy eco --region us-central1 --project exekai
```

Luego abre http://localhost:8080/docs → **POST /preguntar** → **Try it out**, escribe `{"pregunta": "...", "usuario": "tu correo"}` y pulsa **Execute**. Para cerrar el túnel pulsa Ctrl + C; si en Windows no responde, cierra la ventana de la terminal. Para que otra persona pueda probarlo, dale el rol Invocador de Cloud Run (paso 5 de `docs/gcp-preparacion.md`). El despliegue en Cloud Run se hace con la acción **Desplegar ECO de prueba** (pestaña *Actions*), después del paso 5 de [`docs/gcp-preparacion.md`](docs/gcp-preparacion.md).

## Registro de la Consola Exek (fase 3)

Clientes, usuarios, roles, etiquetas, componentes, versiones publicadas e historial viven en el dataset `exekai.exek_registro`. Desde la carpeta `plataforma/`:

```bash
python -m registro.carga_inicial --en-memoria   # muestra lo que cargaría, sin escribir
python -m registro.carga_inicial                # crea las tablas que falten y registra a Districash
python -m registro.sincronizar                  # registra como "en prueba" las versiones nuevas que GitHub dejó en Cloud Storage
python -m pytest registro                       # pruebas en memoria (segundos); requiere pip install -r requirements-pruebas.txt
```

Para correr las mismas pruebas contra BigQuery (tardan unos 45 minutos), define `REGISTRO_PRUEBAS_DATASET=exek_registro_pruebas`.

### Probar la consola en tu computador

```bash
pip install -r plataforma/consola/requirements.txt
python plataforma/consola/demo.py
```

Abre http://localhost:8081. En modo demostración el registro vive en memoria (con Districash cargado), no se escribe en BigQuery y no se crean solicitudes de cambio en GitHub. Para usar el registro real, desde `plataforma/`: `uvicorn consola.app:app --port 8081`.

### Desplegar la consola

En GitHub, pestaña *Actions* → **Desplegar Consola Exek** → **Run workflow**. La acción corre las pruebas del registro, construye la imagen y despliega `consola-exek` en Cloud Run detrás de IAP. Solo entran los miembros del grupo `consola@exek.co`, con su cuenta de Google de Exek.
