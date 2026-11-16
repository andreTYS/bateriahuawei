#!/usr/bin/env python3
"""
Lector completo - Bateria Huawei ESM-48150B1 (instalacion Icr 2 / Pizarro)
----------------------------------------------------------------------------
Lee TODOS los registros en bucle continuo, con reintentos automaticos,
y muestra la corriente/potencia calculada con AMBOS factores posibles
(0.1 y 0.01) lado a lado, para terminar de confirmar cual es el correcto
comparando contra la potencia real que reporte el MPPT/VRM en ese momento.

Configuracion confirmada funcionando:
  - Gateway: 192.168.1.27:8235 (modo "Modbus Simple Protocol Conversion")
  - Direccion Modbus (slave/device id) de la bateria: 214
  - Cable conectado al puerto COM_IN de la bateria (no COM_OUT)

Uso:
    python leer_bateria_icr2_completo.py
"""

import sys
import time

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("Falta pymodbus. Instala con: pip install pymodbus")
    sys.exit(1)

# ---------- CONFIGURACION ----------
GATEWAY_IP = "192.168.1.27"
GATEWAY_PORT = 8235
SLAVE_ID = 214
# ------------------------------------

# Registros: (nombre, direccion, cantidad, factor_escala, unidad, con_signo)
REGISTROS = [
    ("Voltaje de Bateria",     0x0000, 1, 0.01, "V",  False),
    ("Voltaje de Paquete",     0x0001, 1, 0.01, "V",  False),
    ("SOC",                    0x0003, 1, 1,    "%",  False),
    ("SOH",                    0x0004, 1, 1,    "%",  False),
    ("Temp Maxima Celda",      0x0005, 1, 1,    "C",  True),
    ("Temp Minima Celda",      0x0006, 1, 1,    "C",  True),
    ("Estado de Bateria",      0x000A, 1, 1,    "",   False),
    ("Fallos del Sistema",     0x0046, 1, 1,    "bitfield", False),
    ("Protecciones Activas",   0x0048, 1, 1,    "bitfield", False),
    ("Advertencias Activas",   0x0049, 1, 1,    "bitfield", False),
    ("Limite Corriente Desc.", 0x100B, 1, 0.1,  "A",  False),
    ("Limite Corriente Carga", 0x100D, 1, 0.1,  "A",  False),
]

# El registro de corriente se maneja aparte, para mostrar los dos factores
REG_CORRIENTE = 0x0002


def leer_registro(client, addr, count):
    """Compatible con distintas versiones de pymodbus."""
    try:
        return client.read_holding_registers(address=addr, count=count, device_id=SLAVE_ID)
    except TypeError:
        pass
    try:
        return client.read_holding_registers(address=addr, count=count, slave=SLAVE_ID)
    except TypeError:
        pass
    try:
        return client.read_holding_registers(address=addr, count=count, unit=SLAVE_ID)
    except TypeError:
        pass
    return client.read_holding_registers(addr, count)


def leer_con_reintento(client, addr, count, intentos=2):
    """Reintenta una vez, reconectando si hace falta, antes de rendirse."""
    ultimo_error = None
    for _ in range(intentos):
        try:
            resultado = leer_registro(client, addr, count)
            if not resultado.isError():
                return resultado, None
            ultimo_error = "ERROR de lectura"
        except Exception as e:
            ultimo_error = str(e)
            if not client.is_socket_open():
                client.close()
                time.sleep(0.5)
                client.connect()
        time.sleep(0.3)
    return None, ultimo_error


def convertir(valor_crudo, factor, con_signo):
    if con_signo and valor_crudo > 32767:
        valor_crudo -= 65536
    return round(valor_crudo * factor, 2)


def con_signo(valor):
    if valor is None:
        return None
    return valor - 65536 if valor > 32767 else valor


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}.")
        print("Revisa: IP del gateway, Work Mode = TCP Server, y que el cable")
        print("de datos siga en el puerto COM_IN de la bateria.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}, esclavo {SLAVE_ID}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        while True:
            print("=" * 65)
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print("-" * 65)

            # --- Voltaje primero, lo necesitamos para calcular potencia ---
            voltaje = None
            resultado, error = leer_con_reintento(client, 0x0000, 1)
            if not error:
                voltaje = convertir(resultado.registers[0], 0.01, False)
                print(f"{'Voltaje de Bateria':28s} -> {voltaje} V")
            else:
                print(f"{'Voltaje de Bateria':28s} -> ERROR (tras reintento): {error}")

            # --- Corriente: mostrar CRUDO + ambos factores posibles ---
            resultado, error = leer_con_reintento(client, REG_CORRIENTE, 1)
            if not error:
                crudo = con_signo(resultado.registers[0])
                c_01 = round(crudo * 0.1, 2)
                c_001 = round(crudo * 0.01, 2)
                print(f"{'Corriente (crudo)':28s} -> {crudo}")
                print(f"{'  -> con factor 0.1':28s} -> {c_01} A  |  Potencia: {round((voltaje or 0) * c_01)} W")
                print(f"{'  -> con factor 0.01':28s} -> {c_001} A  |  Potencia: {round((voltaje or 0) * c_001)} W")
                print("     (compara estas 2 potencias contra la real del MPPT/VRM)")
            else:
                print(f"{'Corriente':28s} -> ERROR (tras reintento): {error}")

            print("-" * 65)

            # --- Resto de registros ---
            for nombre, addr, count, factor, unidad, signo in REGISTROS:
                resultado, error = leer_con_reintento(client, addr, count)
                if error:
                    print(f"{nombre:28s} -> ERROR (tras reintento): {error}")
                else:
                    crudo = resultado.registers[0]
                    if unidad == "bitfield":
                        print(f"{nombre:28s} -> 0x{crudo:04X} (binario: {crudo:016b})")
                    else:
                        valor = convertir(crudo, factor, signo)
                        print(f"{nombre:28s} -> {valor} {unidad}")
                time.sleep(0.15)

            print()
            time.sleep(3)

    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
