# Traspaso a la fase 2 · I-NA / EXEK

Documento para retomar el trabajo en una sesión nueva de Claude Code conectada a `dinac-maker/EXEK`. Fecha: 22/10/2026. Responsable: Dina Silva (dina.silva@exek.co), Exek.

## Contexto en 6 líneas

1. **I-NA** es la plataforma de Exek: **ECO** (asistente de IA con modelos Claude por Vertex AI) + un **almacén de componentes por cliente** (skills, agentes, artefactos, plugins).
2. Cada cliente es distinto: cada componente pertenece a un solo cliente; personalizar = versión propia. Solo el equipo de Exek crea componentes.
3. **Git guarda qué hace cada componente; la futura Consola Exek guardará quién lo usa, cuándo corre y qué versión está publicada.**
4. Plugin = extensión técnica (conector a un sistema externo). Los indicadores viven dentro de skills y artefactos. Permisos de los roles por etiqueta.
5. Todo en GCP. Proyecto de ECO: **`exekai`**. Datos: `exek-produccion` (solo lectura).
6. Definiciones completas y decisiones con fecha: **`docs/definiciones.md`** (leerlo primero).

## Estado actual del repositorio

- **Fase 1 terminada** (commits "Fase inicial proyecto INA", "MOver a raiz", "Districash v0.2"):
  - `esquemas/` (reglas de fichas), `plantillas/`, `herramientas/` (`validar.py`, `empaquetar.py`, `nuevo.py`), `.github/workflows/validar.yml`.
  - `clientes/districash/`: 2 skills (`deteccion-clientes-perdidos`, `indicadores-ventas`), 1 agente (`monitor-clientes-perdidos`), 1 artefacto (`tablero-control-gerencia`), 1 fuente (`ventas`), casos de prueba. Todo en v0.2.0 y validado.
- **Por confirmar:** que la acción "Validar almacenes" esté en verde en GitHub Actions.
- **Pendiente de GCP** (lo hace un administrador con `docs/gcp-preparacion.md`): servicios en `exekai`, modelos Claude habilitados en Model Garden, cuenta de servicio `eco-prueba`, Workload Identity Federation y variables `GCP_WIF_PROVIDER` / `GCP_SERVICE_ACCOUNT` en GitHub.

## Datos de Districash (tabla de prueba)

- Tabla: `exek-produccion.NewtonAgentSpace.AgentspaceVentas` (1.176.624 filas; facturas del 3/01/2024 al 31/03/2026).
- **Cliente = `cod_cliente_sucursal`** (código|sucursal), que también se muestra como nombre.
- `Fecha_Factura` es TIMESTAMP a medianoche UTC: usar `DATE(Fecha_Factura)`.
- `Ventas_pesos_neto` ya resta devoluciones (filas negativas).
- **Fecha de corte = última factura**, no la fecha de hoy.
- Cliente perdido: más de 60 días sin comprar; la alerta muestra solo los de **hasta 180 días** (1.561 clientes, $2.227 millones de venta mensual perdida; 4.697 históricos).
- Agente: lunes 7:00 a. m. (America/Bogota), a roles Comercial y Gerencia, por correo y portal. Tablero en la etiqueta Gerencia, actualización diaria 6:00 a. m.

## Avance de la fase 2 (22/10/2026)

- GCP preparado (pasos 1 a 4 de `docs/gcp-preparacion.md`); ECO usa la cuenta `eco-prueba`.
- Código en la rama `fase2/eco-prueba`: `plataforma/eco/` (motor, consultas, registro, terminal, servicio web y pruebas), `Dockerfile` y acción de despliegue. Skills de Districash en v0.2.2.
- ECO probado con Vertex AI: pasan los 5 casos y las cifras coinciden con BigQuery (skills v0.2.2).
- Paso 5 de GCP hecho y ECO desplegado en Cloud Run (`eco-districash`, `us-central1`), sin acceso público. **Fase 2 cumplida.**
- Siguiente: fase 3 (Consola Exek). El estado detallado está en la sección 9 de `docs/definiciones.md`.

## Fase 2 · ECO de prueba de Districash

**Objetivo:** que ECO responda preguntas reales de Districash usando sus skills y su tabla de BigQuery. Sin consola ni portal todavía.

| # | Qué | Cómo |
|---|---|---|
| 1 | Preparar GCP | `docs/gcp-preparacion.md` con `EXEKAI_ID=exekai`. Luego cambiar `proyecto_consultas: exekai` en `clientes/districash/exek.yaml` (subir versión no aplica: es el manifiesto). |
| 2 | Motor de ECO | `plataforma/eco/` en Python con el **Claude Agent SDK** usando Vertex AI (`CLAUDE_CODE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_PROJECT_ID=exekai`, región `global`). Carga el paquete que arma `herramientas/empaquetar.py` como plugin local. |
| 3 | Consulta segura de BigQuery | Herramienta propia (servidor MCP en proceso) para ECO: solo `SELECT`, solo tablas declaradas en `fuentes/` del cliente, parámetros de la ficha, `maximum_bytes_billed` del manifiesto, etiquetas de cliente en cada trabajo. Sin acceso a la terminal ni a archivos fuera del paquete. |
| 4 | Registro de ejecuciones | Por cada respuesta: cliente, usuario, componentes usados, consultas, tokens (campo `usage`), costo estimado y resultado. Al inicio, archivo JSONL o tabla en BigQuery de `exekai`. |
| 5 | Pruebas | Script que corre `clientes/districash/pruebas/casos.yaml` contra ECO y verifica `debe_usar`, `debe_mencionar` y `no_debe`. |
| 6 | Desplegar | ECO de prueba en Cloud Run de `exekai`, con la cuenta de servicio `eco-prueba`. |

**Listo cuando:** pasan los 5 casos de prueba y las cifras de ECO coinciden con BigQuery, con la fecha de corte en la respuesta.

**Después:** fase 3 (Consola Exek), fase 4 (programaciones y monitoreo), fase 5 (kit de autor para Claude Code), fase 6 (portal del cliente: ECO, listado de artefactos y de agentes).

## Forma de trabajo acordada

- Primero proponer el plan (qué y cómo), luego escribir el código.
- Todo en español, con lenguaje simple.
- Cada cambio a un componente sube su versión y explica el cambio en `notas_version`; correr `herramientas/validar.py` antes de subir.
- Registrar cada decisión nueva, con fecha, en `docs/definiciones.md`.
