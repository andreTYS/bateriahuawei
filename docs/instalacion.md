# Guía de instalación — nueva obra / nuevo Cerbo

Pasos para replicar esta integración en una instalación nueva.

## 1. Requisitos físicos

- Batería Huawei ESM-48150B1 o ESM-48100B1, con su bus RS485 (RJ45, pines A/B)
  accesible.
- Gateway RS485↔Ethernet (probado con **USR-IOT 304-SOCKA1**).
- Cerbo GX con Venus OS, en la misma red (cable o WiFi) que el gateway.
- Acceso SSH al Cerbo (ver sección 3).

## 2. Configurar el gateway

Desde VCOM o la interfaz web del gateway:

1. Modo de operación: **"Modbus Simple Protocol Conversion"** (modo EDGE
   Gateway) — NO "Transparente".
2. **Work Mode = "TCP Server"** (el Cerbo se conecta a él, no al revés).
3. Puerto TCP: `8235` (o el que se haya configurado — anótalo).
4. Parámetros serie del lado RS485: 9600 baudios, paridad par (EVEN), 1 stop
   bit (valores típicos documentados para estas baterías — confirmar si no
   responde).

**Importante:** el Work Mode y la paridad de este gateway tienden a
revertirse a sus valores de fábrica (TCP Client / paridad NONE) tras un corte
de energía. Revisa esto manualmente cada vez que haya un corte, no hay fix
permanente conocido todavía.

## 3. Acceso SSH al Cerbo

1. En la interfaz del Cerbo: **Ajustes → General → Acceso** (o similar según
   versión), subir el "Access Level" a Superuser/instalador si es necesario.
2. Activar SSH en **Ajustes → General → Acceso remoto** o similar.
3. Conseguir la IP del Cerbo:
   - Si está en una red WiFi conocida: revisar el router, o usar VCOM/ARP.
   - Si cambia constantemente (DHCP): considerar pasar a **IP Manual** en
     Ajustes → Conectividad → WiFi, para evitar tener que recuperarla cada
     vez.
4. Conectar por SSH directo en la LAN (recomendado) en vez del túnel remoto
   de soporte de Victron — el túnel remoto puede estar bloqueado por
   firewalls que cierran puertos no estándar:
   ```
   ssh root@<ip-del-cerbo>
   ```

**Nota:** si el Cerbo tiene cable Ethernet y WiFi activos a la vez en la
misma subred, puede haber enrutamiento incorrecto hacia el gateway.
Desconecta el cable Ethernet y deja solo la interfaz activa que vas a usar.

## 4. Instalar pymodbus en el Cerbo

Venus OS no trae `pip`. Instalación manual:

```bash
cd /tmp
curl -LO https://files.pythonhosted.org/packages/source/p/pymodbus/pymodbus-3.6.9.tar.gz
tar xzf pymodbus-3.6.9.tar.gz
cp -r pymodbus-3.6.9/pymodbus /usr/lib/python3.8/site-packages/   # ajusta la ruta de site-packages según tu version de Venus OS
```

(Si la versión de Python/Venus OS es distinta, ajustar la ruta de destino —
verificar con `python3 -c "import sys; print(sys.path)"`).

## 5. Copiar el driver al Cerbo

Desde tu PC (PowerShell o terminal, en una ventana **nueva**, sin la sesión
SSH abierta):

```bash
scp driver/dbus-huawei-battery.py root@<ip-del-cerbo>:/data/dbus-huawei-battery/dbus-huawei-battery.py
```

Antes de subir, edita en el script las constantes de configuración de la
instalación (al inicio del archivo):

```python
GATEWAY_IP = "..."        # IP del gateway en esta instalación
GATEWAY_PORT = 8235
SLAVE_ID = 214             # confirmar con escanear_direcciones_huawei.py si no es 214
DEVICE_INSTANCE = 42       # único por instalación si hay varias baterías/drivers
```

## 6. Crear el servicio persistente (daemontools)

Por SSH, en el Cerbo:

```bash
mkdir -p /data/dbus-huawei-battery/service/log
chmod +x /data/dbus-huawei-battery/dbus-huawei-battery.py
```

Crear `/data/dbus-huawei-battery/service/run`:
```bash
#!/bin/sh
exec python3 /data/dbus-huawei-battery/dbus-huawei-battery.py
```

Crear `/data/dbus-huawei-battery/service/log/run`:
```bash
#!/bin/sh
exec multilog t s25000 n4 /data/dbus-huawei-battery/log
```

Dar permisos de ejecución:
```bash
chmod +x /data/dbus-huawei-battery/service/run
chmod +x /data/dbus-huawei-battery/service/log/run
```

Activar el servicio:
```bash
ln -s /data/dbus-huawei-battery/service /service/dbus-huawei-battery
```

Verificar que esté corriendo:
```bash
svstat /service/dbus-huawei-battery
# debe mostrar algo como: up (pid 1234) 5 seconds
```

## 7. Hacerlo persistente tras reinicios

Agregar a `/data/rc.local` (crear el archivo si no existe, y darle permisos
de ejecución con `chmod +x /data/rc.local`):

```bash
ln -s /data/dbus-huawei-battery/service /service/dbus-huawei-battery
```

## 8. Seleccionar la batería en la interfaz del Cerbo

**Paso crítico que se olvida fácilmente:** por defecto el Cerbo NO selecciona
automáticamente la batería custom. Hay que elegirla explícitamente:

**Ajustes → Configuración del sistema → Monitor de batería** → seleccionar
"Huawei ESM-48150B1" (o el nombre configurado).

Sin este paso, el panel sigue mostrando datos indirectos calculados por el
MultiPlus en vez de los datos reales de la batería.

## 9. Activar DVCC

**Ajustes → Configuración del sistema → Control de carga (DVCC)** → activar,
y desactivar "Limite la tensión de carga de la batería gestionada" para que
DVCC use el valor dinámico que publica el driver en vez de un límite fijo
manual.

## 10. Validar

```bash
dbus -y com.victronenergy.battery.huawei_42 / GetValue
dbus -y com.victronenergy.battery.huawei_42 /CustomInfo/UltimaLecturaOk GetValue
dbus -y com.victronenergy.battery.huawei_42 /CustomInfo/SegundosDesdeUltimaLectura GetValue
```

Si `/CustomInfo/SegundosDesdeUltimaLectura` crece sin parar, el driver dejó
de poder leer la batería — revisar conexión al gateway (ver
`docs/troubleshooting.md`).

## Desinstalación (si se necesita retirar el driver)

```bash
svc -d /service/dbus-huawei-battery
rm /service/dbus-huawei-battery
# editar /data/rc.local y quitar la línea del symlink, si se agregó
rm -rf /data/dbus-huawei-battery
```

Y en la interfaz del Cerbo, volver a seleccionar el Monitor de batería
original (o automático) en Ajustes → Configuración del sistema.
