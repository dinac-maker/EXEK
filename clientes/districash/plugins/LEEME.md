# Plugins de Districash

Vacío. Los datos de ventas de Districash ya están en BigQuery (`exek-produccion.NewtonAgentSpace.AgentspaceVentas`), así que no se necesita un conector.

Cuando haya que traer datos de otro sistema (por ejemplo, el ERP), cada plugin tendrá su carpeta con:

- `componente.yaml`: sistema de origen, forma de conexión, nombre del secreto en Secret Manager (nunca la credencial), tabla de destino en BigQuery.
- El código o la configuración del conector.

La tabla de destino se registra también en `fuentes/`, para que los skills la puedan leer.
