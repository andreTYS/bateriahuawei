#!/usr/bin/env python3
"""
dbus-huawei-battery (v2.2 - version pulida y robusta)
---------------------------------------------------------
Driver que lee la bateria Huawei ESM-48150B1 via Modbus TCP (a traves del
gateway RS485-Ethernet) y la publica en el dbus de Venus OS como bateria
nativa (com.victronenergy.battery.huawei_42), con proteccion activa para
DVCC en ambos extremos (sobrevoltaje y bajo voltaje).

NINGUN valor de lectura ni escala de conversion fue modificado respecto a
las versiones anteriores ya validadas - todos los cambios de esta version
son de robustez del codigo, no de los datos.

CAMBIOS EN v2.2 (respecto a v2.0):
  1. Se retiro el campo de numero de serie leido/escrito por Modbus. Se
     investigo el tema (ver nota abajo) y se decidio NO implementarlo por
     seguridad: requeriria una secuencia de ESCRITURAS Modbus (no solo
     lecturas) sobre una bateria en operacion, y no es prudente probar
     eso mientras el sistema esta cargando en produccion. El campo
     '/Serial' vuelve a un identificador generico fijo.
  2. Chequeos defensivos de longitud en cada bloque leido (evita
     IndexError si el gateway devolviera un paquete truncado).
  3. Backoff simple antes de reintentar conectar tras un fallo de socket
     (no reintenta la conexion sin pausa).
  4. Cierre ordenado: si el servicio se detiene, marca /Connected=0 y
     cierra el socket limpiamente en vez de simplemente desaparecer.
  5. Numero de version actualizado en el propio dbus para poder
     confirmar desde fuera que instancia esta corriendo.

NOTA sobre el numero de serie (investigacion, no implementado):
  Se encontro un proyecto de la comunidad (ModbusReader_SR, especifico
  para este mismo modelo) que documenta como leerlo: requiere una
  secuencia de autenticacion de 3 pasos con ESCRITURAS en los registros
  37500/37501, seguida de un codigo de funcion Modbus no estandar (FC41,
  similar al concepto de MEI) para pedir bloques de informacion extendida
  (numero de serie, fabricante, fecha). Sin los valores exactos de esa
  secuencia de autenticacion documentados con certeza, e implicando
  escrituras sobre una bateria en produccion, no se aplico aqui. Si en el
  futuro quieres el numero de serie, la ruta mas segura es usar esa
  herramienta de la comunidad de forma aislada (bateria no critica en ese
  momento) y luego, si funciona, copiar el numero manualmente como texto
  fijo en este driver - nunca leerlo en cada ciclo de una bateria activa
  con una secuencia de escritura no verificada al 100%.

CAMBIOS HEREDADOS DE v2.0/v2.1 (siguen vigentes):
  - Lectura por BLOQUES (3 peticiones en vez de registro por registro).
  - Fail-safe: tras STALE_FAILSAFE_SEGUNDOS sin poder refrescar limites,
    se fuerzan valores conservadores en vez de confiar en datos viejos.
  - Proteccion simetrica: sobrevoltaje Y bajo voltaje reducen
    dinamicamente los limites de carga/descarga para DVCC.
  - Bitfields de fallos/protecciones/advertencias publicados en crudo.
  - Marca de tiempo de la ultima lectura exitosa, consultable en
    cualquier momento para saber si el dato que ves esta actualizado:
      dbus -y com.victronenergy.battery.huawei_42 /CustomInfo/SegundosDesdeUltimaLectura GetValue

PENDIENTE (documentado, no resuelto en este driver):
  - CURRENT_SCALE sigue INFERIDO (no confirmado con lectura cruda +
    potencia real conocida). Valida con el script de PC cuando haya
    carga solar activa y compares contra la potencia real del MPPT.
  - El mapeo exacto de cada bit en los registros de fallos/protecciones
    no esta documentado oficialmente - se publican en crudo para
    correlacionarlos manualmente la proxima vez que ocurra una alarma.

Configuracion de esta instalacion (Icr 2 / Pizarro):
  - Gateway: 192.168.1.27:8235 (modo "Modbus Simple Protocol Conversion",
    Work Mode = TCP Server -- revisa esto tras cada corte de energia,
    este gateway tiende a resetear ese valor)
  - Direccion Modbus (slave/device id) de la bateria: 214
  - Cerbo: 192.168.1.22
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
    # pymodbus 2.x tiene ModbusTcpClient en una ruta distinta
    from pymodbus.client.sync import ModbusTcpClient

import dbus
import dbus.mainloop.glib
try:
    from gi.repository import GLib
except ImportError:
    import gobject as GLib

# ================== CONFIGURACION DE RED (AJUSTA A TU INSTALACION) ==================
GATEWAY_IP = "192.168.18.148"
GATEWAY_PORT = 8235
SLAVE_ID = 214
POLL_INTERVAL_MS = 3000
DEVICE_INSTANCE = 42
MODBUS_TIMEOUT_S = 2
MAX_FALLOS_SEGUIDOS = 5          # tras cuantos fallos SEGUIDOS se marca /Connected=0
STALE_FAILSAFE_SEGUNDOS = 300    # 5 min sin poder refrescar limites -> modo fail-safe
RECONEXION_ESPERA_S = 2          # pausa antes de reintentar conectar tras un fallo

# --- Escalas de conversion de los registros crudos ---
VOLTAGE_SCALE = 0.01   # VALIDADO (4851 crudo = 48.51V, confirmado en pruebas reales)
CURRENT_SCALE = 0.01   # INFERIDO, pendiente de confirmar con leer_crudo.py

# --- Umbrales de SOBREVOLTAJE (independientes del bitfield de protecciones) ---
VOLTAJE_ADVERTENCIA_ALTA = 56.4
VOLTAJE_ALARMA_ALTA = 57.5
VOLTAJE_RECUPERACION_ALTA = 55.5

# --- Umbrales de BAJO VOLTAJE (proteccion simetrica del lado de descarga) ---
VOLTAJE_ADVERTENCIA_BAJA = 46.0
VOLTAJE_ALARMA_BAJA = 44.0
VOLTAJE_RECUPERACION_BAJA = 47.0

# --- Limites de voltaje/corriente de CARGA publicados para DVCC ---
MAX_CHARGE_VOLTAGE_NORMAL = 55.0
MAX_CHARGE_VOLTAGE_EN_ADVERTENCIA = 54.0
MAX_CHARGE_VOLTAGE_EN_ALARMA = 52.0

# --- Limites de corriente de DESCARGA publicados para DVCC ---
# (multiplican el valor que reporta la propia bateria en 0x100B; en
# advertencia/alarma de bajo voltaje se reduce mas alla de eso)
FACTOR_DESCARGA_NORMAL = 1.0
FACTOR_DESCARGA_EN_ADVERTENCIA = 0.5
FACTOR_DESCARGA_EN_ALARMA = 0.1

# --- Valores conservadores de FAIL-SAFE (si se pierde comunicacion con
#     los limites por demasiado tiempo, se usan estos en vez de seguir
#     confiando en el ultimo dato conocido) ---
FAILSAFE_MAX_CHARGE_VOLTAGE = 53.0
FAILSAFE_MAX_CHARGE_CURRENT = 5.0
FAILSAFE_MAX_DISCHARGE_CURRENT = 5.0
# =======================================================================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dbus-huawei-battery")


class HuaweiBatteryDriver:
    def __init__(self):
        self._client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=MODBUS_TIMEOUT_S)
        self._service = self._crear_servicio_dbus()
        self._conectar_modbus()

        self._fallos_seguidos = 0
        self._alarma_alta_activa = False
        self._alarma_baja_activa = False

        # Marca de tiempo de la ultima vez que refrescamos limites con exito.
        # Si pasa demasiado tiempo sin poder refrescar, entramos en fail-safe.
        self._ultimo_refresco_limites = time.monotonic()
        self._en_failsafe = False

        # Marca de tiempo (legible) de la ultima lectura exitosa del bloque
        # principal (voltaje/SOC/corriente) - para diagnosticar si el
        # panel muestra datos "congelados" vs recien leidos.
        self._ultima_lectura_ok = None

    def _crear_servicio_dbus(self):
        svc = VeDbusService(f'com.victronenergy.battery.huawei_{DEVICE_INSTANCE}',
                             register=False)

        svc.add_path('/Mgmt/ProcessName', __file__)
        svc.add_path('/Mgmt/ProcessVersion', '2.2')
        svc.add_path('/Mgmt/Connection', f'Modbus TCP {GATEWAY_IP}:{GATEWAY_PORT}')

        svc.add_path('/DeviceInstance', DEVICE_INSTANCE)
        svc.add_path('/ProductId', 0)
        svc.add_path('/ProductName', 'Huawei ESM-48150B1')
        svc.add_path('/CustomName', 'Huawei ESM-48150B1')
        svc.add_path('/FirmwareVersion', '2.2')
        svc.add_path('/HardwareVersion', '1.0')
        svc.add_path('/Connected', 1)
        svc.add_path('/Serial', f'huawei-esm-{DEVICE_INSTANCE}')

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

        # Datos crudos para investigacion/correlacion futura (texto hex)
        svc.add_path('/CustomInfo/FallosRaw', '0x0000')
        svc.add_path('/CustomInfo/ProteccionesRaw', '0x0000')
        svc.add_path('/CustomInfo/AdvertenciasRaw', '0x0000')
        svc.add_path('/CustomInfo/EnFailsafe', 0)
        # Marca de tiempo (texto legible) de la ULTIMA lectura exitosa del
        # bloque principal (voltaje/SOC/corriente). Consultala siempre que
        # dudes si el dato que ves esta actualizado o congelado:
        #   dbus -y com.victronenergy.battery.huawei_42 /CustomInfo/UltimaLecturaOk GetValue
        svc.add_path('/CustomInfo/UltimaLecturaOk', 'nunca')
        svc.add_path('/CustomInfo/SegundosDesdeUltimaLectura', 0)

        svc.register()
        return svc

    def _conectar_modbus(self):
        if not self._client.connect():
            log.error(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}")
            return False
        return True

    def _leer_bloque(self, addr, count):
        """Lee `count` registros consecutivos desde `addr` en una sola peticion.

        IMPORTANTE: en algunas versiones de pymodbus (confirmado en 2.5.3),
        pasar un parametro de nombre incorrecto (ej. 'device_id') NO lanza
        TypeError - se acepta silenciosamente y se IGNORA, y la peticion
        se manda con el esclavo por defecto equivocado, devolviendo un
        error de "No response" en vez de una excepcion de Python. Por eso
        hay que revisar isError() despues de CADA intento, no solo
        capturar excepciones."""
        for kwargs_intento in (
            {"device_id": SLAVE_ID},
            {"slave": SLAVE_ID},
            {"unit": SLAVE_ID},
        ):
            try:
                res = self._client.read_holding_registers(address=addr, count=count, **kwargs_intento)
            except TypeError:
                continue
            except Exception as e:
                log.debug(f"Fallo leyendo bloque {addr} con {kwargs_intento}: {e}")
                continue
            if res is not None and not res.isError():
                return res.registers
        return None

    @staticmethod
    def _con_signo(valor):
        if valor is None:
            return None
        return valor - 65536 if valor > 32767 else valor

    def _evaluar_alarma_alta(self, voltaje):
        """Sobrevoltaje: reduce MaxChargeVoltage dinamicamente antes de que
        la bateria tenga que protegerse por su cuenta."""
        if voltaje >= VOLTAJE_ALARMA_ALTA:
            self._service['/Alarms/HighVoltage'] = 2
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_EN_ALARMA
            if not self._alarma_alta_activa:
                log.warning(f"ALARMA sobrevoltaje: {voltaje:.2f}V >= {VOLTAJE_ALARMA_ALTA}V "
                            f"- limite de carga -> {MAX_CHARGE_VOLTAGE_EN_ALARMA}V")
            self._alarma_alta_activa = True
        elif voltaje >= VOLTAJE_ADVERTENCIA_ALTA:
            self._service['/Alarms/HighVoltage'] = 1
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_EN_ADVERTENCIA
        elif voltaje <= VOLTAJE_RECUPERACION_ALTA:
            if self._alarma_alta_activa:
                log.info(f"Alarma alta despejada: {voltaje:.2f}V - limite vuelve a "
                         f"{MAX_CHARGE_VOLTAGE_NORMAL}V")
            self._service['/Alarms/HighVoltage'] = 0
            self._service['/Info/MaxChargeVoltage'] = MAX_CHARGE_VOLTAGE_NORMAL
            self._alarma_alta_activa = False
        # Zona intermedia: se mantiene el ultimo limite (histeresis)

    def _evaluar_alarma_baja(self, voltaje, limite_desc_base):
        """Bajo voltaje: reduce MaxDischargeCurrent dinamicamente, en vez
        de esperar a que la bateria se proteja sola por sub-descarga."""
        if voltaje <= VOLTAJE_ALARMA_BAJA:
            self._service['/Alarms/LowVoltage'] = 2
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_EN_ALARMA
            if not self._alarma_baja_activa:
                log.warning(f"ALARMA bajo voltaje: {voltaje:.2f}V <= {VOLTAJE_ALARMA_BAJA}V "
                            f"- limite de descarga reducido al {FACTOR_DESCARGA_EN_ALARMA*100:.0f}%")
            self._alarma_baja_activa = True
        elif voltaje <= VOLTAJE_ADVERTENCIA_BAJA:
            self._service['/Alarms/LowVoltage'] = 1
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_EN_ADVERTENCIA
        elif voltaje >= VOLTAJE_RECUPERACION_BAJA:
            if self._alarma_baja_activa:
                log.info(f"Alarma baja despejada: {voltaje:.2f}V - limite de descarga normal")
            self._service['/Alarms/LowVoltage'] = 0
            self._service['/Info/MaxDischargeCurrent'] = limite_desc_base * FACTOR_DESCARGA_NORMAL
            self._alarma_baja_activa = False
        # Zona intermedia: se mantiene el ultimo limite publicado (histeresis)

    def _aplicar_failsafe_si_corresponde(self):
        """Si llevamos demasiado tiempo sin poder refrescar los limites de
        corriente/voltaje, dejamos de confiar en el ultimo valor conocido
        y forzamos valores conservadores por precaucion."""
        segundos_sin_refresco = time.monotonic() - self._ultimo_refresco_limites

        if segundos_sin_refresco >= STALE_FAILSAFE_SEGUNDOS:
            if not self._en_failsafe:
                log.error(
                    f"FAIL-SAFE activado: {segundos_sin_refresco:.0f}s sin poder "
                    f"refrescar limites. Forzando valores conservadores."
                )
            self._service['/Info/MaxChargeVoltage'] = FAILSAFE_MAX_CHARGE_VOLTAGE
            self._service['/Info/MaxChargeCurrent'] = FAILSAFE_MAX_CHARGE_CURRENT
            self._service['/Info/MaxDischargeCurrent'] = FAILSAFE_MAX_DISCHARGE_CURRENT
            self._service['/Alarms/StaleData'] = 2
            self._service['/CustomInfo/EnFailsafe'] = 1
            self._en_failsafe = True
        else:
            if self._en_failsafe:
                log.info("Fail-safe despejado: limites vuelven a calcularse normalmente")
            self._en_failsafe = False
            self._service['/CustomInfo/EnFailsafe'] = 0

    def actualizar(self):
        # Publica cuantos segundos han pasado desde la ultima lectura
        # exitosa, en cada ciclo (exista o no exista lectura nueva ahora).
        if self._ultima_lectura_ok is not None:
            segundos = int((datetime.now() - self._ultima_lectura_ok).total_seconds())
            self._service['/CustomInfo/SegundosDesdeUltimaLectura'] = segundos

        try:
            if not self._client.is_socket_open():
                if not self._conectar_modbus():
                    time.sleep(RECONEXION_ESPERA_S)

            # Bloque 1: voltaje(0x0000), voltaje_paquete(0x0001), corriente(0x0002),
            #           soc(0x0003), soh(0x0004), temp_max(0x0005) -> 6 registros
            bloque1 = self._leer_bloque(0x0000, 6)

            # Bloque 2: limite_desc(0x100B), (0x100C sin usar), limite_carga(0x100D)
            bloque2 = self._leer_bloque(0x100B, 3)

            # Bloque 3: fallos(0x0046), (0x0047 sin usar), protecciones(0x0048),
            #           advertencias(0x0049) -> 4 registros
            bloque3 = self._leer_bloque(0x0046, 4)

            # Chequeo defensivo: si el gateway devolviera menos registros de
            # los esperados (paquete truncado), lo tratamos como fallo en
            # vez de arriesgarnos a un IndexError leyendo posiciones que no
            # llegaron.
            if bloque1 is not None and len(bloque1) < 6:
                log.debug(f"Bloque1 truncado: recibidos {len(bloque1)}/6 registros")
                bloque1 = None

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

                if bloque2 is not None and len(bloque2) < 3:
                    log.debug(f"Bloque2 truncado: recibidos {len(bloque2)}/3 registros")
                    bloque2 = None

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
                    # No pudimos refrescar los limites esta vez - la funcion
                    # de failsafe decide si ya paso demasiado tiempo
                    self._aplicar_failsafe_si_corresponde()
                    if not self._en_failsafe:
                        self._service['/Alarms/StaleData'] = 1

                if bloque3 is not None and len(bloque3) < 4:
                    log.debug(f"Bloque3 truncado: recibidos {len(bloque3)}/4 registros")
                    bloque3 = None

                if bloque3 is not None:
                    fallos_raw = bloque3[0]
                    protecciones_raw = bloque3[2]
                    advertencias_raw = bloque3[3]
                    self._service['/CustomInfo/FallosRaw'] = f"0x{fallos_raw:04X}"
                    self._service['/CustomInfo/ProteccionesRaw'] = f"0x{protecciones_raw:04X}"
                    self._service['/CustomInfo/AdvertenciasRaw'] = f"0x{advertencias_raw:04X}"
                    if protecciones_raw != 0:
                        log.warning(f"Proteccion activa (bitfield crudo): 0x{protecciones_raw:04X}")

                self._service['/Connected'] = 1
                log.info(
                    f"OK - V:{voltaje:.2f} SOC:{soc}% I:{corriente:.2f}A "
                    f"P:{voltaje*corriente:.0f}W failsafe:{self._en_failsafe}"
                )

            else:
                self._fallos_seguidos += 1
                log.warning(f"Sin respuesta del gateway/bateria (fallo #{self._fallos_seguidos})")
                self._aplicar_failsafe_si_corresponde()
                if self._fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                    self._service['/Connected'] = 0

        except Exception as e:
            self._fallos_seguidos += 1
            log.error(f"Error actualizando (fallo #{self._fallos_seguidos}): {e}")
            self._aplicar_failsafe_si_corresponde()
            if self._fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                self._service['/Connected'] = 0

        return True

    def cerrar(self):
        """Cierre ordenado: marca la bateria como desconectada y libera el
        socket, para que quien este mirando el dbus vea /Connected=0 en
        vez de un servicio que simplemente desaparece sin avisar."""
        try:
            self._service['/Connected'] = 0
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass
        log.info("Driver detenido, conexion cerrada de forma ordenada.")


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    driver = HuaweiBatteryDriver()
    GLib.timeout_add(POLL_INTERVAL_MS, driver.actualizar)
    log.info("Driver Huawei battery v2.2 iniciado. Publicando en dbus...")

    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        driver.cerrar()


if __name__ == "__main__":
    main()

"""
--------------------------------------------------------------------------
COMO ACTUALIZAR EN EL CERBO (via SSH):
--------------------------------------------------------------------------
1. Detener el servicio:
     svc -d /service/dbus-huawei-battery

2. Desde una ventana NUEVA de PowerShell (sin SSH), subir el archivo:
     scp "C:\\ruta\\dbus-huawei-battery-v2.2.py" root@192.168.1.22:/data/dbus-huawei-battery/dbus-huawei-battery.py

3. Dar permisos y reiniciar:
     chmod +x /data/dbus-huawei-battery/dbus-huawei-battery.py
     svc -u /service/dbus-huawei-battery

4. Verificar:
     svstat /service/dbus-huawei-battery
     dbus -y com.victronenergy.battery.huawei_42 / GetValue

5. Solo despues de confirmar que corre bien, en la interfaz del Cerbo:
   Ajustes -> Configuracion del sistema -> Control de carga ->
   desactivar "Limite la tension de carga de la bateria gestionada"
   (para que DVCC use el valor dinamico del driver en vez del fijo manual)

RECORDATORIO: tras cada corte de energia del GATEWAY (no del Cerbo),
revisa en http://192.168.1.27 -> Port Parameter -> Work Mode = "TCP Server"
--------------------------------------------------------------------------
"""
