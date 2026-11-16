# Problemas recurrentes y soluciones

Problemas reales encontrados a lo largo de varias instalaciones, con su
diagnóstico y solución (o el estado de "no tiene fix permanente, revisar
manualmente").

## 1. `ModuleNotFoundError: cannot import name 'ModbusTcpClient' from 'pymodbus.client'`

En Venus OS con pymodbus 2.5.3, la ruta correcta es distinta a la de
versiones modernas.

**Fix:** el driver ya maneja esto con:
```python
try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    from pymodbus.client.sync import ModbusTcpClient
```

## 2. Bug crítico de pymodbus 2.5.3 con el parámetro `device_id`

pymodbus 2.5.3 **no lanza `TypeError`** al recibir un parámetro de nombre
incorrecto como `device_id` — lo ignora silenciosamente, y la petición
Modbus se manda con el esclavo por defecto equivocado. El resultado es un
**error de protocolo Modbus** (`isError() == True`), no una excepción
Python, así que una cadena simple de `try/except TypeError` nunca llega a
probar la siguiente alternativa (`slave=` o `unit=`).

**Síntoma:** el servicio aparece como "up" (corriendo) en `svstat`, pero la
batería nunca aparece como opción en el menú "Monitor de batería" del Cerbo,
y los logs muestran errores de "No response" constantes.

**Fix:** revisar `isError()` después de CADA intento, no solo capturar
excepciones:
```python
for kwargs_intento in ({"device_id": SLAVE_ID}, {"slave": SLAVE_ID}, {"unit": SLAVE_ID}):
    try:
        res = client.read_holding_registers(address=addr, count=count, **kwargs_intento)
    except TypeError:
        continue
    except Exception:
        continue
    if res is not None and not res.isError():
        return res.registers
return None
```
Ya implementado en `driver/dbus-huawei-battery.py` (función `_leer_bloque`).

## 3. `No module named pip` / `No module named tomllib`

Venus OS no trae pip instalado.

**Fix:** instalación manual de pymodbus sin pip ni `get-pip.py` — descargar
el `.tar.gz` con `curl`, extraer con `tar`, y copiar la carpeta directamente
a `site-packages` (ver `docs/instalacion.md`, paso 4).

## 4. El gateway revierte su configuración tras un corte de energía

**Síntoma:** tras un corte de luz, el driver deja de poder conectar
(`Connection refused`), aunque antes funcionaba.

**Causa:** el gateway suele volver a su Work Mode de fábrica ("TCP Client")
en vez de mantener "TCP Server". De forma similar, la paridad del puerto
serie puede revertir de EVEN a NONE.

**No hay fix permanente conocido.** Hay que revisar manualmente
`http://<ip-del-gateway>` → Port Parameter, tras cada corte de energía del
gateway (no del Cerbo).

## 5. La IP del Cerbo cambia constantemente (WiFi + DHCP)

**Síntoma:** hay que volver a "cazar" la IP del Cerbo cada vez (ARP, VCOM,
VRM) para poder entrar por SSH.

**Fix recomendado (no siempre aplicado):** cambiar a **IP Manual/estática**
en el Cerbo, en Ajustes → Conectividad → WiFi, en vez de dejarlo en
"Automático" (DHCP).

## 6. Túnel SSH remoto de Victron bloqueado

**Síntoma:** el túnel de soporte remoto de Victron (puertos no estándar como
48911, 36921, 43495) da timeout constante.

**Causa:** firewalls de la red del cliente bloqueando esos puertos no
estándar (confirmado con `Test-NetConnection`). El puerto 22 puede estar
abierto pero solo acepta autenticación por llave pública, no usable para
acceso directo.

**Fix:** usar **SSH directo por LAN/WiFi** (conectado a la misma red que el
Cerbo) en vez del túnel remoto.

## 7. Dos interfaces de red activas en la misma subred

**Síntoma:** el driver no puede alcanzar el gateway aunque la red "funcione".

**Causa:** el Cerbo tiene cable Ethernet y WiFi conectados a la vez, ambos en
la misma subred, causando enrutamiento incorrecto.

**Fix:** desconectar el cable Ethernet y dejar solo la interfaz WiFi activa
(o viceversa, según cuál esté realmente conectada al gateway).

## 8. SOC "congelado" (dato viejo mostrado como si fuera actual)

**Síntoma:** el panel muestra un SOC que no coincide con el real (ej. 68%
en el panel vs 37% leído directo desde PC).

**Causa:** el driver puede seguir reportando el último valor exitoso aunque
haya dejado de actualizar hace mucho tiempo, sin marcarlo como obsoleto.

**Fix:** agregadas las rutas `/CustomInfo/UltimaLecturaOk` y
`/CustomInfo/SegundosDesdeUltimaLectura` (desde v2.1), para poder verificar
en cualquier momento qué tan reciente es el dato:
```bash
dbus -y com.victronenergy.battery.huawei_42 /CustomInfo/SegundosDesdeUltimaLectura GetValue
```
Además, el mecanismo de fail-safe (ver README) fuerza valores conservadores
si pasan más de `STALE_FAILSAFE_SEGUNDOS` (300s por defecto) sin poder
refrescar los límites.

## 9. Factor de escala de corriente no confirmado

**Síntoma:** en una obra el factor `0.01` pareció encajar bien; en otra, ni
`0.01` ni `0.1` coincidían limpio contra la potencia reportada por el
MultiPlus (el cálculo inverso dio ~0.03).

**Estado:** sigue pendiente. Validar con una medición externa confiable
(pinza amperimétrica) en vez de comparaciones indirectas contra el
MultiPlus, usando `scripts-validacion/leer_crudo.py` para ver el valor crudo
sin escalar.

## 10. Batería con alarma (LED ALM + sonido) sin daño físico visible

**Síntoma:** LED de alarma rojo activo y sonido, sin olor, calor ni
hinchazón visible en la batería.

**Diagnóstico:** se observó el bitfield de protecciones (`0x0048`) con el
valor `0x2000` (bit 13) activo durante uno de estos eventos — el significado
exacto de ese bit no está documentado oficialmente por Huawei.

**Pendiente de confirmar:** si el reset manual (botón MANUAL ON/OFF,
mantenido 5-15 segundos) despeja esta alarma específica.
