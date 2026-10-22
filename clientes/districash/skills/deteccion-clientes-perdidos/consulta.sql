-- Districash · Detección de clientes perdidos · v0.1.0
-- Fuente: fuentes/ventas.yaml
-- Parámetro: @umbral_dias (INT64)
-- Fecha de corte: última factura de la tabla (los datos no siempre llegan hasta hoy).

WITH base AS (
  SELECT
    CAST(CAST(cod_cliente AS INT64) AS STRING) AS cliente_id,
    DATE(Fecha_Factura) AS fecha,
    Ventas_pesos_neto AS valor,
    Segmento_Cliente,
    Ciudad,
    Vendedor_Actual_Cliente
  FROM `exek-produccion.NewtonAgentSpace.AgentspaceVentas`
  WHERE cod_cliente IS NOT NULL
),
corte AS (
  SELECT MAX(fecha) AS fecha_corte FROM base
),
ultima AS (
  SELECT
    cliente_id,
    MAX(fecha) AS ultima_compra,
    ANY_VALUE(Segmento_Cliente) AS segmento,
    ANY_VALUE(Ciudad) AS ciudad,
    ANY_VALUE(Vendedor_Actual_Cliente) AS vendedor
  FROM base
  WHERE valor > 0
  GROUP BY cliente_id
),
historia AS (
  SELECT
    b.cliente_id,
    SUM(b.valor) / 12 AS compra_promedio_mensual
  FROM base AS b
  JOIN ultima AS u USING (cliente_id)
  WHERE b.fecha > DATE_SUB(u.ultima_compra, INTERVAL 12 MONTH)
  GROUP BY b.cliente_id
)
SELECT
  u.cliente_id,
  u.segmento,
  u.ciudad,
  u.vendedor,
  u.ultima_compra,
  DATE_DIFF(c.fecha_corte, u.ultima_compra, DAY) AS dias_sin_comprar,
  ROUND(h.compra_promedio_mensual) AS compra_promedio_mensual,
  c.fecha_corte
FROM ultima AS u
JOIN historia AS h USING (cliente_id)
CROSS JOIN corte AS c
WHERE DATE_DIFF(c.fecha_corte, u.ultima_compra, DAY) > @umbral_dias
ORDER BY compra_promedio_mensual DESC
