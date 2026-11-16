#!/usr/bin/env python3
"""
Lector final - Bateria Huawei ESM-48150B1 via gateway RS485-Ethernet
------------------------------------------------------------------------
Configuracion CONFIRMADA funcionando:
  - Gateway 304-SOCKA1 en modo "Modbus Simple Protocol Conversion" (EDGE Gateway)
  - Puerto serie: 9600 baudios, 8 bits, paridad EVEN, 1 stop bit
  - Direccion Modbus (slave/device id) de la bateria: 214
  - Cable conectado al puerto COM_IN de la bateria (no COM_OUT)

Uso:
    python leer_bateria_huawei_final.py
"""

import sys
import time

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("Falta pymodbus. Instala con: pip install pymodbus")
    sys.exit(1)

# ---------- CONFIGURACION ----------
GATEWAY_IP = "192.168.101.9"
GATEWAY_PORT = 8235
SLAVE_ID = 214
# ------------------------------------

# Registros: (nombre, direccion, cantidad, factor_escala, unidad, con_signo)
# factor_escala: multiplica el valor crudo leido para obtener la unidad real
# con_signo: True si el valor puede ser negativo (ej. corriente en descarga)
REGISTROS = [
    ("Voltaje de Bateria",     0x0000, 1, 0.01, "V",  False),
    ("Voltaje de Paquete",     0x0001, 1, 0.01, "V",  False),
    ("Corriente de Bateria",   0x0002, 1, 0.1,  "A",  True),
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
    """Intenta leer un registro; si falla, reconecta y reintenta una vez mas
    antes de darse por vencido. Devuelve (resultado, error_texto)."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            resultado = leer_registro(client, addr, count)
            if not resultado.isError():
                return resultado, None
            ultimo_error = "ERROR de lectura"
        except Exception as e:
            ultimo_error = str(e)
            # Si la conexion se cerro del lado del gateway, reconectamos
            if not client.is_socket_open():
                client.close()
                time.sleep(0.5)
                client.connect()
        time.sleep(0.3)
    return None, ultimo_error


def convertir(valor_crudo, factor, con_signo):
    """Aplica escala y, si con_signo, interpreta como entero de 16 bits con signo
    (para valores como corriente/temperatura que pueden ser negativos)."""
    if con_signo and valor_crudo > 32767:
        valor_crudo -= 65536
    return round(valor_crudo * factor, 2)


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}, esclavo {SLAVE_ID}\n")

    try:
        while True:
            print("-" * 55)
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            for nombre, addr, count, factor, unidad, con_signo in REGISTROS:
                resultado, error = leer_con_reintento(client, addr, count)
                if error:
                    print(f"{nombre:28s} -> ERROR (tras reintento): {error}")
                else:
                    crudo = resultado.registers[0]
                    if unidad == "bitfield":
                        print(f"{nombre:28s} -> 0x{crudo:04X} (binario: {crudo:016b})")
                    else:
                        valor = convertir(crudo, factor, con_signo)
                        print(f"{nombre:28s} -> {valor} {unidad}")
                time.sleep(0.2)
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
