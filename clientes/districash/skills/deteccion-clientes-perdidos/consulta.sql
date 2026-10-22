-- Districash · Detección de clientes perdidos · v0.2.0
-- Fuente: fuentes/ventas.yaml (datos de prueba)
-- Parámetros: @umbral_dias (INT64) y @ventana_dias (INT64)
-- Cliente = cod_cliente_sucursal (código|sucursal): cada sucursal se trata como un cliente.
-- Fecha de corte: última factura de la tabla.
-- Devuelve los clientes perdidos dentro de la ventana: más de @umbral_dias y hasta
-- @ventana_dias sin comprar. La columna perdidos_historico cuenta todos los perdidos.

WITH base AS (
  SELECT
    cod_cliente_sucursal AS cliente,
    DATE(Fecha_Factura) AS fecha,
    Ventas_pesos_neto AS valor,
    Segmento_Cliente,
    Ciudad,
    Vendedor_Actual_Cliente
  FROM `exek-produccion.NewtonAgentSpace.AgentspaceVentas`
  WHERE cod_cliente_sucursal IS NOT NULL
),
corte AS (
  SELECT MAX(fecha) AS fecha_corte FROM base
),
ultima AS (
  SELECT
    cliente,
    MAX(fecha) AS ultima_compra,
    ANY_VALUE(Segmento_Cliente) AS segmento,
    ANY_VALUE(Ciudad) AS ciudad,
    ANY_VALUE(Vendedor_Actual_Cliente) AS vendedor
  FROM base
  WHERE valor > 0
  GROUP BY cliente
),
historia AS (
  SELECT
    b.cliente,
    SUM(b.valor) / 12 AS compra_promedio_mensual
  FROM base AS b
  JOIN ultima AS u USING (cliente)
  WHERE b.fecha > DATE_SUB(u.ultima_compra, INTERVAL 12 MONTH)
  GROUP BY b.cliente
),
perdidos AS (
  SELECT
    u.cliente,
    u.segmento,
    u.ciudad,
    u.vendedor,
    u.ultima_compra,
    DATE_DIFF(c.fecha_corte, u.ultima_compra, DAY) AS dias_sin_comprar,
    ROUND(h.compra_promedio_mensual) AS compra_promedio_mensual,
    c.fecha_corte,
    COUNT(*) OVER () AS perdidos_historico
  FROM ultima AS u
  JOIN historia AS h USING (cliente)
  CROSS JOIN corte AS c
  WHERE DATE_DIFF(c.fecha_corte, u.ultima_compra, DAY) > @umbral_dias
)
SELECT *
FROM perdidos
WHERE dias_sin_comprar <= @ventana_dias
ORDER BY compra_promedio_mensual DESC
