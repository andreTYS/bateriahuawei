#!/usr/bin/env python3
"""
Lector de prueba - Bateria Huawei ESM-48150B1 via gateway RS485-Ethernet
--------------------------------------------------------------------------
Ahora usando Modbus TCP (a traves del gateway 304-SOCKA1 en modo
"Modbus Simple Protocol Conversion"), en vez de serial directo.

Uso:
    1. Instala la libreria: pip install pymodbus==3.6.9 --break-system-packages
    2. Ajusta GATEWAY_IP y GATEWAY_PORT abajo si cambian.
    3. Ejecuta: python3 leer_bateria_huawei_tcp.py
"""

import sys
import time

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("Falta pymodbus. Instala con: pip install pymodbus --break-system-packages")
    sys.exit(1)

# ---------- CONFIGURACION - AJUSTA ESTO ----------
GATEWAY_IP = "192.168.101.9"
GATEWAY_PORT = 8235
SLAVE_ID = 1  # Direccion Modbus de la bateria (prueba 1, 2, 21... si no responde)
# --------------------------------------------------

# Registros a leer: (nombre, direccion, cantidad_de_registros, factor_escala, unidad)
REGISTROS = [
    ("Voltaje de Bateria",     0x0000, 1, 1, "V"),
    ("Voltaje de Paquete",     0x0001, 1, 1, "V"),
    ("Corriente de Bateria",   0x0002, 1, 1, "A"),
    ("SOC",                    0x0003, 1, 1, "%"),
    ("SOH",                    0x0004, 1, 1, "%"),
    ("Temp Maxima Celda",      0x0005, 1, 1, "C"),
    ("Temp Minima Celda",      0x0006, 1, 1, "C"),
    ("Estado de Bateria",      0x000A, 1, 1, ""),
    ("Fallos del Sistema",     0x0046, 1, 1, "bitfield"),
    ("Protecciones Activas",   0x0048, 1, 1, "bitfield"),
    ("Advertencias Activas",   0x0049, 1, 1, "bitfield"),
    ("Limite Corriente Desc.", 0x100B, 1, 1, "A"),
    ("Limite Corriente Carga", 0x100D, 1, 1, "A"),
]


def leer_registro(client, addr, count):
    """Intenta leer con distintos nombres de parametro segun version de pymodbus.
    pymodbus 3.14+ usa 'device_id'; versiones 3.x anteriores usan 'slave';
    versiones viejas (2.x) usan 'unit'."""
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
    # Ultimo recurso: solo address y count (sin id de esclavo, usa el default del cliente)
    return client.read_holding_registers(addr, count)


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}. Revisa la IP/puerto del gateway.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}, consultando esclavo {SLAVE_ID}...\n")

    try:
        while True:
            print("-" * 50)
            for nombre, addr, count, factor, unidad in REGISTROS:
                try:
                    resultado = leer_registro(client, addr, count)
                    if resultado.isError():
                        print(f"{nombre:28s} -> ERROR de lectura")
                    else:
                        valor = resultado.registers[0] * factor
                        print(f"{nombre:28s} -> {valor} {unidad}")
                except Exception as e:
                    print(f"{nombre:28s} -> excepcion: {e}")
                time.sleep(0.1)
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
