# Mapa de registros Modbus — Batería Huawei ESM-48150B1 / ESM-48100B1

Registros leídos vía **Holding Registers** (función Modbus 0x03), accedidos
por Modbus TCP a través del gateway RS485↔Ethernet. Todos son de 16 bits.

**Dirección Modbus (slave/device id) de la batería:** `214` — encontrada
escaneando (ver `scripts-validacion/escanear_direcciones_huawei.py`); no es
la dirección por defecto típica (1), así que si se reemplaza el equipo o se
agrega uno nuevo, vuelve a escanear antes de asumir que es 214.

## Bloque 1 — Estado general (0x0000, 6 registros)

| Dirección | Nombre | Escala | Unidad | Estado |
|---|---|---|---|---|
| 0x0000 | Voltaje de batería | 0.01 | V | **Validado** (4851 crudo = 48.51V, confirmado con lectura real) |
| 0x0001 | Voltaje de paquete | 0.01 | V | No usado activamente en el driver |
| 0x0002 | Corriente de batería (con signo, complemento a 2) | 0.01 | A | **Inferido, pendiente de confirmar**. Validar con pinza amperimétrica + comparación contra potencia real del MPPT/MultiPlus |
| 0x0003 | SOC | 1 | % | Validado |
| 0x0004 | SOH | 1 | % | Validado |
| 0x0005 | Temperatura máxima de celda (con signo) | 1 | °C | Validado |
| 0x0006 | Temperatura mínima de celda (con signo) | 1 | °C | Disponible, no usado activamente |
| 0x000A | Estado de batería | - | - | Disponible, no decodificado |

## Bloque 2 — Límites de carga/descarga (0x100B, 3 registros)

| Dirección | Nombre | Escala | Unidad | Estado |
|---|---|---|---|---|
| 0x100B | Límite de corriente de descarga | 0.1 | A | Validado |
| 0x100C | (sin usar) | - | - | - |
| 0x100D | Límite de corriente de carga | 0.1 | A | Validado |

## Bloque 3 — Fallos / protecciones / advertencias (0x0046, 4 registros)

| Dirección | Nombre | Escala | Unidad | Estado |
|---|---|---|---|---|
| 0x0046 | Fallos del sistema (bitfield) | - | bitfield | Publicado en crudo (hex), bits no mapeados oficialmente |
| 0x0047 | (sin usar) | - | - | - |
| 0x0048 | Protecciones activas (bitfield) | - | bitfield | Publicado en crudo. Se observó `0x2000` (bit 13) activo durante una alarma real en Hostal la Chosita — significado exacto sin confirmar |
| 0x0049 | Advertencias activas (bitfield) | - | bitfield | Publicado en crudo |

## Registros NO implementados (investigados, descartados por seguridad)

El proyecto comunitario [ModbusReader_SR](https://github.com/nestorcal/ModbusReader_SR)
(específico para este modelo) documenta una vía para leer el **número de
serie**, fabricante y fecha de fabricación:

1. Secuencia de autenticación de 3 pasos, con **escrituras** Modbus en los
   registros `37500` / `37501`.
2. Tras autenticar, uso de un **código de función Modbus no estándar (FC41)**,
   similar al concepto de MEI, para pedir bloques de información extendida.

**No se implementó en este driver** porque:
- Requiere escribir sobre una batería en operación, no solo leer.
- No se tienen los valores exactos de la secuencia de autenticación
  confirmados al 100%.
- El riesgo de interferir con una batería activa en producción no se
  justifica solo para obtener un número de serie.

Si en el futuro se necesita, la ruta más segura es usar esa herramienta de la
comunidad de forma aislada (con la batería no crítica en ese momento) y, si
funciona, copiar el número manualmente como texto fijo en el driver — nunca
leerlo en cada ciclo de una batería activa con una secuencia de escritura no
verificada.

## Nota sobre direcciones alternativas

En instalaciones futuras, si la dirección 214 no responde, probar con el
script `scripts-validacion/escanear_direcciones_huawei.py`, que recorre
`[214, 1, 2, 3, 10, 21, 40, 100, 200, 247, 0]`.
