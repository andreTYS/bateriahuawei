# Driver Huawei ESM ↔ Victron Cerbo GX

Driver no oficial que permite integrar baterías de litio **Huawei ESM** (modelos
**ESM-48150B1** y **ESM-48100B1**) con sistemas **Victron Energy** (Cerbo GX /
Venus OS), ya que Huawei no ofrece comunicación nativa con el ecosistema Victron.

Desarrollado por **Moqueguasoft** para el cliente **Inversiones ICR S.R.L.**,
validado en varias instalaciones físicas reales.

## ¿Qué hace?

El Cerbo GX no puede hablar directamente con la batería Huawei (que usa Modbus
RTU por RS485 con un mapa de registros propio, no estándar). Este driver:

1. Lee la batería por **Modbus TCP**, a través de un gateway RS485↔Ethernet.
2. Traduce esos datos (voltaje, SOC, SOH, temperatura, corriente, límites de
   carga/descarga, fallos/protecciones) a las rutas D-Bus que Venus OS espera
   de una batería nativa.
3. Publica el dispositivo como `com.victronenergy.battery.huawei_<instancia>`,
   para que el Cerbo lo pueda seleccionar como **Monitor de batería** y
   habilitar **DVCC** (control dinámico de voltaje/corriente de carga).
4. Aplica protección activa por software (sobrevoltaje y bajo voltaje) con
   histéresis, reduciendo dinámicamente los límites de carga/descarga antes
   de que la propia batería tenga que protegerse sola.
5. Tiene un mecanismo de **fail-safe**: si pasa demasiado tiempo sin poder
   refrescar los límites desde la batería, deja de confiar en el último dato
   conocido y fuerza valores conservadores.

## Arquitectura

```
[Batería Huawei ESM] --RS485--> [Gateway RS485-Ethernet, ej. USR-IOT 304-SOCKA1]
                                          |
                                     Modbus TCP (red local)
                                          |
                                   [Cerbo GX / Venus OS]
                                          |
                      dbus-huawei-battery.py (este driver, corre como servicio)
                                          |
                                     D-Bus (Venus OS)
                                          |
                         Cerbo UI + VRM + DVCC lo ven como batería nativa
```

El gateway debe configurarse en modo **"Modbus Simple Protocol Conversion"**
(también llamado modo EDGE Gateway), con **Work Mode = "TCP Server"**.

## Contenido del repositorio

| Carpeta/archivo | Contenido |
|---|---|
| `driver/dbus-huawei-battery.py` | Driver principal (v2.2, versión corregida) — correr en el Cerbo |
| `driver/dbus-huawei-battery-multi.py` | Variante para leer varias baterías a la vez (un gateway por batería) |
| `driver/watchdog-gateway-huawei.py` | Script opcional de monitoreo del gateway (no reconfigura automáticamente) |
| `scripts-validacion/` | Scripts para correr desde una PC y probar la comunicación Modbus de forma independiente al Cerbo |
| `docs/registros-modbus.md` | Mapa de registros Modbus usados, con su escala y estado de validación |
| `docs/instalacion.md` | Guía paso a paso: acceso SSH, instalación del driver, puesta en marcha |
| `docs/troubleshooting.md` | Problemas recurrentes encontrados en campo y cómo resolverlos |

## Instalaciones donde está desplegado

- **Uno** (primera instalación)
- **Icr 2 / Pizarro**
- **Obra 3 / Hostal la Chosita**

Cada instalación tiene su propia configuración de red (IP del gateway, IP del
Cerbo, DEVICE_INSTANCE) — ver la sección de configuración al inicio de cada
copia del driver desplegada, y `docs/instalacion.md`.

## Estado conocido / pendientes

- El **factor de escala de corriente** (`CURRENT_SCALE`) está inferido en
  `0.01` pero no confirmado con una medición externa confiable (pinza
  amperimétrica) en todas las instalaciones — ver `docs/registros-modbus.md`.
- El mapeo exacto de cada **bit de fallo/protección/advertencia** (registros
  `0x0046`, `0x0048`, `0x0049`) no está documentado oficialmente por Huawei;
  se publican en crudo (hex) para poder correlacionarlos manualmente la
  próxima vez que ocurra una alarma real.
- La lectura del **número de serie** de la batería se investigó (requiere una
  secuencia de autenticación con escrituras Modbus + función custom FC41,
  documentada por el proyecto comunitario
  [ModbusReader_SR](https://github.com/nestorcal/ModbusReader_SR)) pero
  **no se implementó** por seguridad: implica escribir sobre una batería en
  producción sin tener los valores de autenticación confirmados al 100%.

## Licencia / uso

Desarrollo interno de Moqueguasoft para Inversiones ICR S.R.L. Úsalo bajo tu
propio criterio — es un driver no oficial, no respaldado por Huawei ni por
Victron Energy.
