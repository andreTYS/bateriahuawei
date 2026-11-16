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
# Lista de direcciones a probar. Cubre las mas comunes en equipos Huawei/telecom.
SLAVE_IDS_A_PROBAR = [214, 1, 2, 3, 10, 21, 40, 100, 200, 247, 0]
# --------------------------------------------------

# Solo probamos un registro (voltaje) durante el escaneo, para ir rapido
REGISTRO_PRUEBA = ("Voltaje de Bateria", 0x0000, 1)

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


def leer_registro(client, addr, count, slave_id):
    """Intenta leer con distintos nombres de parametro segun version de pymodbus.
    pymodbus 3.14+ usa 'device_id'; versiones 3.x anteriores usan 'slave';
    versiones viejas (2.x) usan 'unit'."""
    try:
        return client.read_holding_registers(address=addr, count=count, device_id=slave_id)
    except TypeError:
        pass
    try:
        return client.read_holding_registers(address=addr, count=count, slave=slave_id)
    except TypeError:
        pass
    try:
        return client.read_holding_registers(address=addr, count=count, unit=slave_id)
    except TypeError:
        pass
    return client.read_holding_registers(addr, count)


def escanear_direcciones(client):
    """Prueba cada direccion Modbus de la lista y reporta cual responde."""
    nombre, addr, count = REGISTRO_PRUEBA
    encontrado = False
    for slave_id in SLAVE_IDS_A_PROBAR:
        print(f"Probando direccion {slave_id}...", end=" ", flush=True)
        try:
            resultado = leer_registro(client, addr, count, slave_id)
            if resultado.isError():
                print("sin respuesta (error Modbus)")
            else:
                print(f"*** RESPONDIO *** -> {nombre}: {resultado.registers[0]}")
                encontrado = True
        except Exception as e:
            print(f"sin respuesta ({type(e).__name__})")
        time.sleep(0.3)
    return encontrado


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=2)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}. Revisa la IP/puerto del gateway.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}. Escaneando direcciones Modbus...\n")
    print("-" * 50)

    encontrado = escanear_direcciones(client)

    print("-" * 50)
    if not encontrado:
        print("\nNinguna direccion respondio. Esto normalmente significa:")
        print("  - Problema fisico en el bus RS485 (cableado, puerto COM_IN/OUT)")
        print("  - Baudrate/paridad no coincide con la bateria")
        print("  - La bateria no esta activa (revisa el LED)")
    else:
        print("\nSe encontro respuesta. Anota la direccion y usala en el script principal.")

    client.close()


if __name__ == "__main__":
    main()
