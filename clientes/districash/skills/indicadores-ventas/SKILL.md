---
name: indicadores-ventas
description: Calcula los indicadores de ventas de Districash por mes (venta neta, acumulado del año, variación contra el año anterior, clientes activos, ticket promedio, frecuencia de compra, clientes nuevos). Úsala para preguntas sobre cómo van las ventas, comparaciones entre meses o años, ticket, frecuencia o número de clientes.
---

# Indicadores de ventas · Districash

## Cómo calcular
1. Ejecuta la consulta del skill con la herramienta `ejecutar_skill` (`skill_id: indicadores-ventas`, `max_filas: 60`). Devuelve una fila por mes con todos los indicadores, desde enero de 2024 hasta el mes de la fecha de corte; la columna `fecha_corte` es la última factura registrada.
2. Para **clientes perdidos** usa la skill `deteccion-clientes-perdidos`; no la recalcules aquí.

## Definiciones
Cliente = cada código de cliente y sucursal (`cod_cliente_sucursal`, por ejemplo `7290|12`).

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
- Di siempre cuál es la fecha de corte de los datos y qué periodo usaste.
- **Periodos relativos** (definición de Districash): se cuentan desde el **mes de la fecha de corte**, no desde hoy.
  - "Este mes": el mes de la fecha de corte. Si la fecha de corte no es el último día del mes, avisa que ese mes está incompleto.
  - "El mes pasado": **el mes anterior al mes de la fecha de corte**, aunque el mes de la fecha de corte esté completo. Ejemplo: con corte el 31/03/2026, el mes pasado es febrero de 2026.
  - "Este trimestre" / "el trimestre pasado": el trimestre calendario que contiene la fecha de corte / el anterior.
  - "Este año" / "el año pasado": el año de la fecha de corte hasta la fecha de corte / el año anterior completo (para comparar, usa el mismo periodo en los dos años, como se explica abajo).
  - Si no indican periodo, usa el mes de la fecha de corte.
- Para comparar un año contra el anterior usa el mismo periodo en los dos años (por ejemplo, enero a marzo); para el ticket promedio de un periodo de varios meses, recalcúlalo con `consulta_libre` (venta neta del periodo ÷ facturas del periodo) en lugar de promediar los meses.
- **Facturas** = números de factura distintos con al menos una línea de venta positiva: las devoluciones (notas crédito) **no** cuentan como factura, igual que en `consulta.sql`. En SQL: `COUNT(DISTINCT IF(Ventas_pesos_neto > 0, Numero_Factura, NULL))`. La venta neta sí resta las devoluciones.
- Clientes nuevos de los primeros meses de 2024 están inflados, porque los datos empiezan en enero de 2024; adviértelo si los consultan.
- Cifras en pesos colombianos sin decimales; porcentajes con un decimal.
- Para tendencias, muestra los últimos 12 meses.
