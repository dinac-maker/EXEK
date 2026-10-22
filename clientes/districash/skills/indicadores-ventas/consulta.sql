-- Districash · Indicadores de ventas · v0.2.0
-- Cliente = cod_cliente_sucursal (código|sucursal).
-- Fuente: fuentes/ventas.yaml
-- Una fila por mes, desde el inicio de los datos hasta el mes de la fecha de corte.
-- Clientes activos: con compra (sin devoluciones) en los 60 días previos al cierre del mes.

WITH base AS (
  SELECT
    cod_cliente_sucursal AS cliente_id,
    Numero_Factura AS factura_id,
    DATE(Fecha_Factura) AS fecha,
    DATE_TRUNC(DATE(Fecha_Factura), MONTH) AS mes,
    Ventas_pesos_neto AS valor
  FROM `exek-produccion.NewtonAgentSpace.AgentspaceVentas`
  WHERE cod_cliente_sucursal IS NOT NULL
),
compras AS (
  SELECT * FROM base WHERE valor > 0
),
por_mes AS (
  SELECT
    mes,
    SUM(valor) AS venta_neta_mes
  FROM base
  GROUP BY mes
),
facturacion AS (
  SELECT
    mes,
    COUNT(DISTINCT factura_id) AS facturas,
    COUNT(DISTINCT cliente_id) AS clientes_que_compraron
  FROM compras
  GROUP BY mes
),
activos AS (
  SELECT m.mes, COUNT(DISTINCT c.cliente_id) AS clientes_activos
  FROM (SELECT DISTINCT mes FROM base) AS m
  JOIN compras AS c
    ON c.fecha BETWEEN DATE_SUB(LAST_DAY(m.mes), INTERVAL 59 DAY) AND LAST_DAY(m.mes)
  GROUP BY m.mes
),
nuevos AS (
  SELECT mes_primera AS mes, COUNT(*) AS clientes_nuevos
  FROM (SELECT cliente_id, MIN(mes) AS mes_primera FROM compras GROUP BY cliente_id)
  GROUP BY mes_primera
)
SELECT
  p.mes,
  ROUND(p.venta_neta_mes) AS venta_neta_mes,
  ROUND(SUM(p.venta_neta_mes) OVER (PARTITION BY EXTRACT(YEAR FROM p.mes) ORDER BY p.mes)) AS venta_acumulada_anio,
  ROUND(SAFE_DIVIDE(p.venta_neta_mes, LAG(p.venta_neta_mes, 12) OVER (ORDER BY p.mes)) - 1, 4) AS variacion_anio_ant,
  a.clientes_activos,
  ROUND(SAFE_DIVIDE(p.venta_neta_mes, f.facturas)) AS ticket_promedio,
  ROUND(SAFE_DIVIDE(f.facturas, f.clientes_que_compraron), 2) AS frecuencia_compra,
  IFNULL(n.clientes_nuevos, 0) AS clientes_nuevos
FROM por_mes AS p
LEFT JOIN facturacion AS f USING (mes)
LEFT JOIN activos AS a USING (mes)
LEFT JOIN nuevos AS n USING (mes)
ORDER BY p.mes
