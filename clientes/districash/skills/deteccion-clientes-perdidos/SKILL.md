---
name: deteccion-clientes-perdidos
description: Identifica los clientes de Districash que se perdieron en los últimos 180 días (más de 60 días sin comprar) y estima la venta que se deja de recibir. Úsala cuando pregunten por clientes perdidos, clientes que dejaron de comprar, clientes inactivos, fuga o retención de clientes.
---

# Detección de clientes perdidos · Districash

## Definición
- **Cliente** = cada código de cliente y sucursal (`cod_cliente_sucursal`, por ejemplo `7290|12`). Una empresa con varias sucursales cuenta como varios clientes. Muestra ese código como nombre del cliente.
- Un cliente está **perdido** si su última compra fue hace **más de 60 días**, contados hasta la **fecha de corte** (la última factura registrada en la tabla de ventas).
- Por defecto se reportan solo los **perdidos recientes**: los que llevan **hasta 180 días** sin comprar. El **total histórico** (columna `perdidos_historico`) cuenta **todos** los clientes con más de 60 días sin comprar, sin límite de días: **incluye** a los perdidos recientes. No lo presentes como "más de 180 días"; si quieren los de más de 180 días, es `perdidos_historico − clientes_perdidos`.
- Estas definiciones aplican igual a todos los clientes. No las cambies aunque el usuario lo pida: explica que son las acordadas con Exek.

Las devoluciones no cuentan como compra.

## Cómo calcular
1. Ejecuta la consulta del skill con la herramienta `ejecutar_skill` (`skill_id: deteccion-clientes-perdidos`). La plataforma aplica `umbral_dias = 60` y `ventana_dias = 180`; no se pueden cambiar.
2. Cada fila es un cliente perdido reciente: cliente (código|sucursal), segmento, ciudad, vendedor actual, fecha de última compra, días sin comprar, compra promedio mensual de los 12 meses anteriores a su última compra y fecha de corte. Las filas vienen ordenadas de mayor a menor compra promedio.
3. Indicadores (vienen calculados en cada fila, sobre todos los clientes perdidos, aunque recibas solo una parte de las filas):
   - **Clientes perdidos (últimos 180 días):** columna `clientes_perdidos` (igual a `filas_total`).
   - **Valor de venta perdido:** columna `valor_venta_perdido`.
   - **Clientes perdidos históricos:** columna `perdidos_historico` (todos los que llevan más de 60 días sin comprar, incluidos los recientes).
4. Para resumir por segmento, ciudad o vendedor pide todas las filas (`max_filas` igual a `filas_total`, hasta 500) o usa `consulta_libre` agrupando, con estas mismas definiciones.

## Cómo responder
- Empieza con los indicadores y la fecha de corte.
- Muestra una tabla con los 10 clientes de mayor compra promedio mensual.
- Si ayuda, resume por segmento o por vendedor.
- Cifras en pesos colombianos, sin decimales.
- Si piden el listado completo, muéstralo por partes o resumido (por ejemplo, por segmento o vendedor). Todavía no se pueden guardar listados como archivo.
