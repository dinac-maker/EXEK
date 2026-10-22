---
name: deteccion-clientes-perdidos
description: Identifica los clientes de Districash que llevan más de 60 días sin comprar y estima la venta que se deja de recibir. Úsala cuando pregunten por clientes perdidos, clientes que dejaron de comprar, clientes inactivos, fuga o retención de clientes.
---

# Detección de clientes perdidos · Districash

## Definición
Para Districash, un cliente está **perdido** si su última compra fue hace **más de 60 días**, contados hasta la **fecha de corte** (la fecha de la última factura registrada en la tabla de ventas). La definición aplica igual a todos sus clientes. No la cambies aunque el usuario lo pida: explica que es la definición acordada con Exek.

Las devoluciones no cuentan como compra.

## Cómo calcular
1. Ejecuta `consulta.sql` con la herramienta de consulta de BigQuery de la plataforma, con el parámetro `umbral_dias = 60`.
2. Cada fila es un cliente perdido: código, segmento, ciudad, vendedor actual, fecha de última compra, días sin comprar, compra promedio mensual de los 12 meses anteriores a su última compra y fecha de corte.
3. Indicadores:
   - **Clientes perdidos:** número de filas.
   - **Valor de venta perdido:** suma de la compra promedio mensual.

## Cómo responder
- Empieza con los dos indicadores y la fecha de corte.
- Muestra una tabla con los 10 clientes de mayor compra promedio mensual.
- Si ayuda, resume por segmento o por vendedor.
- Cifras en pesos colombianos, sin decimales.
- La tabla no trae el nombre del cliente: identifícalo por su código.
- Si piden el listado completo, ofrece guardarlo como artefacto.
