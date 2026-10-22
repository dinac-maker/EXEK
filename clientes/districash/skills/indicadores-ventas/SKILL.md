---
name: indicadores-ventas
description: Calcula los indicadores de ventas de Districash por mes (venta neta, acumulado del año, variación contra el año anterior, clientes activos, ticket promedio, frecuencia de compra, clientes nuevos). Úsala para preguntas sobre cómo van las ventas, comparaciones entre meses o años, ticket, frecuencia o número de clientes.
---

# Indicadores de ventas · Districash

## Cómo calcular
1. Ejecuta `consulta.sql` con la herramienta de consulta de BigQuery de la plataforma. Devuelve una fila por mes con todos los indicadores, desde enero de 2024 hasta el mes de la fecha de corte (la última factura registrada).
2. Para **clientes perdidos** usa la skill `deteccion-clientes-perdidos`; no la recalcules aquí.

## Definiciones
| Indicador | Fórmula |
|---|---|
| Venta neta del mes | Suma de `Ventas_pesos_neto` del mes (las devoluciones restan) |
| Venta acumulada del año | Suma de la venta neta desde el 1 de enero hasta el mes |
| Variación contra el año anterior | Venta del mes ÷ venta del mismo mes del año anterior − 1 |
| Clientes activos | Clientes con al menos una factura en los 60 días previos al cierre del mes |
| Ticket promedio | Venta neta del mes ÷ número de facturas del mes |
| Frecuencia de compra | Facturas del mes ÷ clientes que compraron en el mes |
| Clientes nuevos | Clientes cuya primera factura es de ese mes |

## Cómo responder
- Usa el último mes con datos, salvo que pidan otro periodo, y di cuál es la fecha de corte de los datos.
- Clientes nuevos de los primeros meses de 2024 están inflados, porque los datos empiezan en enero de 2024; adviértelo si los consultan.
- Cifras en pesos colombianos sin decimales; porcentajes con un decimal.
- Para tendencias, muestra los últimos 12 meses.
