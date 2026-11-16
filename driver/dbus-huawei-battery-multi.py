#!/usr/bin/env python3
"""
dbus-huawei-battery-multi (v1.0)
------------------------------------
Version multi-bateria del driver: lee y publica VARIAS baterias Huawei
ESM-48150B1 al mismo tiempo, cada una conectada a su propio gateway
RS485-Ethernet (IP distinta), como servicios dbus independientes.

Requisito de arquitectura: cada bateria necesita su PROPIO gateway (no
se puede compartir un mismo bus RS485 entre varias baterias con la
misma direccion Modbus - hay colision). Si tus 3 baterias responden
todas en el Slave ID 214, es porque cada una esta/debe estar en un bus
separado con su propio gateway.

Toda la logica de lectura, escalas, alarmas y fail-safe es la MISMA que
la version v2.2 de una sola bateria - simplemente se instancia una vez
por cada bateria configurada en BATERIAS abajo.

Configuracion: edita la lista BATERIAS con los datos reales de cada
bateria/gateway antes de instalar.
"""

import os
import sys
import time
import logging
from datetime import datetime

sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))
sys.path.insert(1, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')

from vedbus import VeDbusService
try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    from pymodbus.client.sync import ModbusTcpClient

import dbus
import dbus.mainloop.glib
try:
    from gi.repository import GLib
except ImportError:
    import gobject as GLib

# ================== CONFIGURACION: UNA ENTRADA POR BATERIA ==================
# device_instance debe ser UNICO para cada bateria (no repetir numeros)
BATERIAS = [
    {
        "nombre": "Huawei ESM-48150B1 #1",
        "gateway_ip": "192.168.1.27",   # <-- AJUSTA: IP del gateway 1
        "gateway_port": 8235,
        "slave_id": 214,
        "device_instance": 42,
    },
    {
        "nombre": "Huawei ESM-48150B1 #2",
        "gateway_ip": "192.168.1.28",   # <-- AJUSTA: IP del gateway 2
        "gateway_port": 8235,
        "slave_id": 214,
        "device_instance": 43,
    },
    {
        "nombre": "Huawei ESM-48150B1 #3",
        "gateway_ip": "192.168.1.29",   # <-- AJUSTA: IP del gateway 3
        "gateway_port": 8235,
        "slave_id": 214,
        "device_instance": 44,
    },
]

POLL_INTERVAL_MS = 3000
MODBUS_TIMEOUT_S = 2
MAX_FALLOS_SEGUIDOS = 5
STALE_FAILSAFE_SEGUNDOS = 300

VOLTAGE_SCALE = 0.01
CURRENT_SCALE = 0.01   # pendiente de validar, igual que en la version single

VOLTAJE_ADVERTENCIA_ALTA = 56.4
VOLTAJE_ALARMA_ALTA = 57.5
VOLTAJE_RECUPERACION_ALTA = 55.5

VOLTAJE_ADVERTENCIA_BAJA = 46.0
VOLTAJE_ALARMA_BAJA = 44.0
VOLTAJE_RECUPERACION_BAJA = 47.0

MAX_CHARGE_VOLTAGE_NORMAL = 55.0
MAX_CHARGE_VOLTAGE_EN_ADVERTENCIA = 54.0
MAX_CHARGE_VOLTAGE_EN_ALARMA = 52.0

FACTOR_DESCARGA_NORMAL = 1.0
FACTOR_DESCARGA_EN_ADVERTENCIA = 0.5
FACTOR_DESCARGA_EN_ALARMA = 0.1

FAILSAFE_MAX_CHARGE_VOLTAGE = 53.0
FAILSAFE_MAX_CHARGE_CURRENT = 5.0
FAILSAFE_MAX_DISCHARGE_CURRENT = 5.0
# ================================================================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dbus-huawei-battery-multi")


class HuaweiBatteryDriver:
    """Misma logica que la version single-bateria v2.2, parametrizada
    para poder instanciarse varias veces (una por bateria)."""

    def __init__(self, nombre, gateway_ip, gateway_port, slave_id, device_instance):
        self.nombre = nombre
        self.gateway_ip = gateway_ip
        self.gateway_port = gateway_port
        self.slave_id = slave_id
        self.device_instance = device_instance

        self._client = ModbusTcpClient(gateway_ip, port=gateway_port, timeout=MODBUS_TIMEOUT_S)
        self._service = self._crear_servicio_dbus()
        self._conectar_modbus()

        self._fallos_seguidos = 0
        self._alarma_alta_activa = False
        self._alarma_baja_activa = False
        self._ultimo_refresco_limites = time.monotonic()
        self._en_failsafe = False
        self._ultima_lectura_ok = None

    def _crear_servicio_dbus(self):
        svc = VeDbusService(
            f'com.victronenergy.battery.huawei_{self.device_instance}',
            register=False)

        svc.add_path('/Mgmt/ProcessName', __file__)
        svc.add_path('/Mgmt/ProcessVersion', '1.0-multi')
        svc.add_path('/Mgmt/Connection', f'Modbus TCP {self.gateway_ip}:{self.gateway_port}')

        svc.add_path('/DeviceInstance', self.device_instance)
        svc.add_path('/ProductId', 0)
        svc.add_path('/ProductName', self.nombre)
        svc.add_path('/CustomName', self.nombre)
        svc.add_path('/FirmwareVersion', '1.0-multi')
        svc.add_path('/HardwareVersion', '1.0')
        svc.add_path('/Connected', 1)
        svc.add_path('/Serial', f'huawei-{self.device_instance}')

        svc.add_path('/Dc/0/Voltage', None, writeable=False, gettextcallback=lambda p, v: f"{v:.2f}V")
        svc.add_path('/Dc/0/Current', None, writeable=False, gettextcallback=lambda p, v: f"{v:.2f}A")
        svc.add_path('/Dc/0/Power', None, writeable=False, gettextcallback=lambda p, v: f"{v:.0f}W")
        svc.add_path('/Dc/0/Temperature', None, writeable=False)
        svc.add_path('/Soc', None, writeable=False)
        svc.add_path('/Soh', None, writeable=False)

        svc.add_path('/Info/MaxChargeCurrent', None, writeable=False)
        svc.add_path('/Info/MaxDischargeCurrent', None, writeable=False)
        svc.add_path('/Info/MaxChargeVoltage', MAX_CHARGE_VOLTAGE_NORMAL, writeable=False)

        svc.add_path('/Alarms/LowVoltage', 0)
        svc.add_path('/Alarms/HighVoltage', 0)
        svc.add_path('/Alarms/LowSoc', 0)
        svc.add_path('/Alarms/HighTemperature', 0)
        svc.add_path('/Alarms/LowTemperature', 0)
        svc.add_path('/Alarms/StaleData', 0)

        svc.add_path('/CustomInfo/FallosRaw', '0x0000')
        svc.add_path('/CustomInfo/ProteccionesRaw', '0x0000')
        svc.add_path('/CustomInfo/AdvertenciasRaw', '0x0000')
        svc.add_path('/CustomInfo/EnFailsafe', 0)
        svc.add_path('/CustomInfo/UltimaLecturaOk', 'nunca')
        svc.add_path('/CustomInfo/SegundosDesdeUltimaLectura', 0)

        svc.register()
        return svc

    def _conectar_modbus(self):
        if not self._client.connect():
            log.error(f"[{self.nombre}] No se pudo conectar a {self.gateway_ip}:{self.gateway_port}")
            return False
        return True

    def _leer_bloque(self, addr, count):
        try:
            try:
                res = self._client.read_holding_registers(address=addr, count=count, device_id=self.slave_id)
            except TypeError:
                try:
                    res = self._client.read_holding_registers(address=addr, count=count, slave=self.slave_id)
                except TypeError:
                    res = self._client.read_holding_registers(addr, count, unit=self.slave_id)
            if res.isError():
                return None
            if len(res.registers) < count:
                return None
            return res.registers
        except Exception as e:
            log.debug(f"[{self.nombre}] Fallo leyendo bloque {addr}: {e}")
            return None

    @staticmethod
    def _con_signo(valor):
        if valor is None:
            return None
        return valor - 65536 if valor > 32767 else valor

    def _evaluar_alarma_alta(self, voltaje):
        if voltaje >= VOLTAJE_ALARMA_ALTA:
            self._service['/Alarms/HighVoltage'] = 2
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_EN_ALARMA
            if not self._alarma_alta_activa:
                log.warning(f"[{self.nombre}] ALARMA sobrevoltaje: {voltaje:.2f}V")
            self._alarma_alta_activa = True
        elif voltaje >= VOLTAJE_ADVERTENCIA_ALTA:
            self._service['/Alarms/HighVoltage'] = 1
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_EN_ADVERTENCIA
        elif voltaje <= VOLTAJE_RECUPERACION_ALTA:
            self._service['/Alarms/HighVoltage'] = 0
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_NORMAL
            self._alarma_alta_activa = False

    def _evaluar_alarma_baja(self, voltaje, limite_desc_base):
        if voltaje <= VOLTAJE_ALARMA_BAJA:
            self._service['/Alarms/LowVoltage'] = 2
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_EN_ALARMA
            if not self._alarma_baja_activa:
                log.warning(f"[{self.nombre}] ALARMA bajo voltaje: {voltaje:.2f}V")
            self._alarma_baja_activa = True
        elif voltaje <= VOLTAJE_ADVERTENCIA_BAJA:
            self._service['/Alarms/LowVoltage'] = 1
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_EN_ADVERTENCIA
        elif voltaje >= VOLTAJE_RECUPERACION_BAJA:
            self._service['/Alarms/LowVoltage'] = 0
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_NORMAL
            self._alarma_baja_activa = False

    def _aplicar_failsafe_si_corresponde(self):
        segundos = time.monotonic() - self._ultimo_refresco_limites
        if segundos >= STALE_FAILSAFE_SEGUNDOS:
            if not self._en_failsafe:
                log.error(f"[{self.nombre}] FAIL-SAFE activado ({segundos:.0f}s sin refrescar)")
            self._service['/Info/MaxChargeVoltage'] = FAILSAFE_MAX_CHARGE_VOLTAGE
            self._service['/Info/MaxChargeCurrent'] = FAILSAFE_MAX_CHARGE_CURRENT
            self._service['/Info/MaxDischargeCurrent'] = FAILSAFE_MAX_DISCHARGE_CURRENT
            self._service['/Alarms/StaleData'] = 2
            self._service['/CustomInfo/EnFailsafe'] = 1
            self._en_failsafe = True
        else:
            if self._en_failsafe:
                log.info(f"[{self.nombre}] Fail-safe despejado")
            self._en_failsafe = False
            self._service['/CustomInfo/EnFailsafe'] = 0

    def actualizar(self):
        if self._ultima_lectura_ok is not None:
            seg = int((datetime.now() - self._ultima_lectura_ok).total_seconds())
            self._service['/CustomInfo/SegundosDesdeUltimaLectura'] = seg

        try:
            if not self._client.is_socket_open():
                self._conectar_modbus()

            bloque1 = self._leer_bloque(0x0000, 6)
            bloque2 = self._leer_bloque(0x100B, 3)
            bloque3 = self._leer_bloque(0x0046, 4)

            if bloque1 is not None:
                self._fallos_seguidos = 0
                self._ultima_lectura_ok = datetime.now()
                self._service['/CustomInfo/UltimaLecturaOk'] = self._ultima_lectura_ok.strftime('%Y-%m-%d %H:%M:%S')

                voltaje = bloque1[0] * VOLTAGE_SCALE
                corriente = self._con_signo(bloque1[2]) * CURRENT_SCALE
                soc = bloque1[3]
                soh = bloque1[4]
                temp = self._con_signo(bloque1[5])

                self._service['/Dc/0/Voltage'] = voltaje
                self._service['/Dc/0/Current'] = corriente
                self._service['/Dc/0/Power'] = voltaje * corriente
                self._service['/Soc'] = max(0, min(soc, 100))
                self._service['/Soh'] = soh
                self._service['/Dc/0/Temperature'] = temp
                self._service['/Alarms/LowSoc'] = 2 if soc < 10 else 0

                if bloque2 is not None:
                    self._ultimo_refresco_limites = time.monotonic()
                    limite_desc_base = bloque2[0] * 0.1
                    limite_carga_base = bloque2[2] * 0.1
                    self._service['/Info/MaxChargeCurrent'] = limite_carga_base
                    self._aplicar_failsafe_si_corresponde()
                    if not self._en_failsafe:
                        self._evaluar_alarma_alta(voltaje)
                        self._evaluar_alarma_baja(voltaje, limite_desc_base)
                        self._service['/Alarms/StaleData'] = 0
                else:
                    self._aplicar_failsafe_si_corresponde()
                    if not self._en_failsafe:
                        self._service['/Alarms/StaleData'] = 1

                if bloque3 is not None:
                    fallos_raw = bloque3[0]
                    protecciones_raw = bloque3[2]
                    advertencias_raw = bloque3[3]
                    self._service['/CustomInfo/FallosRaw'] = f"0x{fallos_raw:04X}"
                    self._service['/CustomInfo/ProteccionesRaw'] = f"0x{protecciones_raw:04X}"
                    self._service['/CustomInfo/AdvertenciasRaw'] = f"0x{advertencias_raw:04X}"
                    if protecciones_raw != 0:
                        log.warning(f"[{self.nombre}] Proteccion activa: 0x{protecciones_raw:04X}")

                self._service['/Connected'] = 1
                log.info(f"[{self.nombre}] OK - V:{voltaje:.2f} SOC:{soc}% I:{corriente:.2f}A")

            else:
                self._fallos_seguidos += 1
                log.warning(f"[{self.nombre}] Sin respuesta (fallo #{self._fallos_seguidos})")
                self._aplicar_failsafe_si_corresponde()
                if self._fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                    self._service['/Connected'] = 0

        except Exception as e:
            self._fallos_seguidos += 1
            log.error(f"[{self.nombre}] Error actualizando (fallo #{self._fallos_seguidos}): {e}")
            self._aplicar_failsafe_si_corresponde()
            if self._fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                self._service['/Connected'] = 0

        return True

    def cerrar(self):
        try:
            self._service['/Connected'] = 0
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    drivers = []
    for cfg in BATERIAS:
        log.info(f"Iniciando driver para {cfg['nombre']} ({cfg['gateway_ip']}:{cfg['gateway_port']})")
        driver = HuaweiBatteryDriver(
            nombre=cfg["nombre"],
            gateway_ip=cfg["gateway_ip"],
            gateway_port=cfg["gateway_port"],
            slave_id=cfg["slave_id"],
            device_instance=cfg["device_instance"],
        )
        drivers.append(driver)
        # Cada bateria se actualiza en su propio timer (evita que una
        # bateria lenta/caida bloquee la lectura de las demas)
        GLib.timeout_add(POLL_INTERVAL_MS, driver.actualizar)

    log.info(f"Driver multi-bateria iniciado con {len(drivers)} bateria(s). Publicando en dbus...")

    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        for d in drivers:
            d.cerrar()
        log.info("Todos los drivers detenidos de forma ordenada.")


if __name__ == "__main__":
    main()

"""
--------------------------------------------------------------------------
INSTALACION EN EL CERBO (via SSH):
--------------------------------------------------------------------------
1. Edita la lista BATERIAS arriba con la IP real de cada gateway antes
   de subir el archivo.

2. Si ya tenias el driver de UNA bateria instalado como servicio, detenlo
   primero (no pueden correr los dos a la vez, competirian por el mismo
   nombre de servicio dbus si usas el mismo device_instance):
     svc -d /service/dbus-huawei-battery

3. Crear carpeta para la version multi (separada, para no pisar la
   version single por si necesitas volver atras):
     mkdir -p /data/dbus-huawei-battery-multi/service/log
     mkdir -p /data/dbus-huawei-battery-multi/log

4. Subir el archivo (desde PowerShell nuevo, sin SSH):
     scp "dbus-huawei-battery-multi.py" root@<ip-cerbo>:/data/dbus-huawei-battery-multi/

5. Permisos y prueba manual:
     chmod +x /data/dbus-huawei-battery-multi/dbus-huawei-battery-multi.py
     python3 /data/dbus-huawei-battery-multi/dbus-huawei-battery-multi.py
   Deberias ver logs "[Huawei ESM-48150B1 #1] OK - V:...", "[#2] OK...",
   "[#3] OK..." intercalados. Ctrl+C para detener la prueba.

6. Si funciona, crear el servicio:
     cat > /data/dbus-huawei-battery-multi/service/run << 'EOF'
     #!/bin/sh
     exec python3 /data/dbus-huawei-battery-multi/dbus-huawei-battery-multi.py
     EOF
     chmod +x /data/dbus-huawei-battery-multi/service/run

     cat > /data/dbus-huawei-battery-multi/service/log/run << 'EOF'
     #!/bin/sh
     exec svlogd -tt /data/dbus-huawei-battery-multi/log
     EOF
     chmod +x /data/dbus-huawei-battery-multi/service/log/run

     ln -s /data/dbus-huawei-battery-multi/service /service/dbus-huawei-battery-multi
     echo 'ln -s /data/dbus-huawei-battery-multi/service /service/dbus-huawei-battery-multi' >> /data/rc.local

7. Verificar:
     svstat /service/dbus-huawei-battery-multi
     dbus -y | grep huawei
   (deberias ver 3 servicios: huawei_42, huawei_43, huawei_44)
--------------------------------------------------------------------------
"""
