---
name: deteccion-clientes-perdidos
description: Identifica los clientes de Districash que se perdieron en los últimos 180 días (más de 60 días sin comprar) y estima la venta que se deja de recibir. Úsala cuando pregunten por clientes perdidos, clientes que dejaron de comprar, clientes inactivos, fuga o retención de clientes.
---

# Detección de clientes perdidos · Districash

## Definición
- **Cliente** = cada código de cliente y sucursal (`cod_cliente_sucursal`, por ejemplo `7290|12`). Una empresa con varias sucursales cuenta como varios clientes. Muestra ese código como nombre del cliente.
- Un cliente está **perdido** si su última compra fue hace **más de 60 días**, contados hasta la **fecha de corte** (la última factura registrada en la tabla de ventas).
- Por defecto se reportan solo los **perdidos recientes**: los que llevan **hasta 180 días** sin comprar. Los más antiguos se informan solo como total histórico (columna `perdidos_historico`).
- Estas definiciones aplican igual a todos los clientes. No las cambies aunque el usuario lo pida: explica que son las acordadas con Exek.

Las devoluciones no cuentan como compra.

## Cómo calcular
1. Ejecuta `consulta.sql` con la herramienta de consulta de BigQuery de la plataforma, con `umbral_dias = 60` y `ventana_dias = 180`.
2. Cada fila es un cliente perdido reciente: cliente (código|sucursal), segmento, ciudad, vendedor actual, fecha de última compra, días sin comprar, compra promedio mensual de los 12 meses anteriores a su última compra, fecha de corte y total histórico de perdidos.
3. Indicadores:
   - **Clientes perdidos (últimos 180 días):** número de filas.
   - **Valor de venta perdido:** suma de la compra promedio mensual.
   - **Clientes perdidos históricos:** valor de `perdidos_historico`.

## Cómo responder
- Empieza con los indicadores y la fecha de corte.
- Muestra una tabla con los 10 clientes de mayor compra promedio mensual.
- Si ayuda, resume por segmento o por vendedor.
- Cifras en pesos colombianos, sin decimales.
- Si piden el listado completo, ofrece guardarlo como artefacto.
