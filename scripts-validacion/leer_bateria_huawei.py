#!/usr/bin/env python3
"""
Lector de prueba - Batería Huawei ESM-48150B1 vía Modbus RTU (RS485)
----------------------------------------------------------------------
Uso:
    1. Conecta el adaptador USB-RS485 a la batería (RJ45 -> A/B) y a tu PC.
    2. Averigua el puerto serie que asignó el sistema:
         - Windows:  revisa "Administrador de dispositivos" -> Puertos (COM y LPT), ej. COM5
         - Linux:    ejecuta `ls /dev/ttyUSB*` (normalmente /dev/ttyUSB0)
    3. Ajusta PORT, BAUDRATE y SLAVE_ID abajo si es necesario.
    4. Instala la librería:  pip install pymodbus==3.6.9 --break-system-packages
    5. Ejecuta:  python3 leer_bateria_huawei.py

Nota: la dirección esclavo (SLAVE_ID) por defecto de estas baterías suele
ser 1, pero si tienes varias en cadena cada una tiene una distinta.
Si no responde con 1, prueba 2, 3, 21, 0... (varía según el firmware).
"""

import sys
import time

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    print("Falta pymodbus. Instala con: pip install pymodbus --break-system-packages")
    sys.exit(1)

# ---------- CONFIGURACION - AJUSTA ESTO ----------
PORT = "/dev/ttyUSB0"   # En Windows sería algo como "COM5"
BAUDRATE = 9600         # Valor típico documentado para estas baterías
PARITY = "N"            # N=None, E=Even, O=Odd -- probar si N no responde
STOPBITS = 1
SLAVE_ID = 1            # Dirección Modbus de la batería
# --------------------------------------------------

# Registros a leer: (nombre, direccion, cantidad_de_registros, factor_escala, unidad)
REGISTROS = [
    ("Voltaje de Batería",     0x0000, 1, 1,    "V"),
    ("Voltaje de Paquete",     0x0001, 1, 1,    "V"),
    ("Corriente de Batería",   0x0002, 1, 1,    "A"),
    ("SOC",                    0x0003, 1, 1,    "%"),
    ("SOH",                    0x0004, 1, 1,    "%"),
    ("Temp Máxima Celda",      0x0005, 1, 1,    "°C"),
    ("Temp Mínima Celda",      0x0006, 1, 1,    "°C"),
    ("Estado de Batería",      0x000A, 1, 1,    ""),
    ("Fallos del Sistema",     0x0046, 1, 1,    "bitfield"),
    ("Protecciones Activas",   0x0048, 1, 1,    "bitfield"),
    ("Advertencias Activas",   0x0049, 1, 1,    "bitfield"),
    ("Límite Corriente Desc.", 0x100B, 1, 1,    "A"),
    ("Límite Corriente Carga", 0x100D, 1, 1,    "A"),
]


def main():
    client = ModbusSerialClient(
        port=PORT,
        baudrate=BAUDRATE,
        parity=PARITY,
        stopbits=STOPBITS,
        bytesize=8,
        timeout=1,
    )

    if not client.connect():
        print(f"No se pudo abrir el puerto {PORT}. Revisa el cable/driver del adaptador.")
        sys.exit(1)

    print(f"Conectado a {PORT} @ {BAUDRATE}bps, consultando esclavo {SLAVE_ID}...\n")

    try:
        while True:
            print("-" * 50)
            for nombre, addr, count, factor, unidad in REGISTROS:
                try:
                    resultado = client.read_holding_registers(
                        address=addr, count=count, slave=SLAVE_ID
                    )
                    if resultado.isError():
                        print(f"{nombre:28s} -> ERROR de lectura")
                    else:
                        valor = resultado.registers[0] * factor
                        print(f"{nombre:28s} -> {valor} {unidad}")
                except Exception as e:
                    print(f"{nombre:28s} -> excepción: {e}")
                time.sleep(0.05)  # pequeña pausa entre consultas
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
