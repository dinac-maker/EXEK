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
