#!/usr/bin/env python3
"""
Lee el valor CRUDO (sin escala) de voltaje y corriente de la bateria
Huawei, para validar (o corregir) el factor de escala de corriente.

Uso: corre esto MIENTRAS haya carga solar real y conocida (revisa el
MPPT/dashboard de VRM para saber cuantos watts esta entregando en ese
momento), y compara contra lo que este script calcula.
"""

import sys
from pymodbus.client import ModbusTcpClient

# ---------- Datos de esta instalacion (Icr 2 / Pizarro) ----------
GATEWAY_IP = "192.168.1.27"
GATEWAY_PORT = 8235
SLAVE_ID = 214
# --------------------------------------------------------------------

def leer(client, addr, count=1):
    try:
        r = client.read_holding_registers(address=addr, count=count, device_id=SLAVE_ID)
    except TypeError:
        try:
            r = client.read_holding_registers(address=addr, count=count, slave=SLAVE_ID)
        except TypeError:
            r = client.read_holding_registers(addr, count)
    if r.isError():
        return None
    return r.registers

def con_signo(v):
    if v is None:
        return None
    return v - 65536 if v > 32767 else v

client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)
if not client.connect():
    print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}")
    sys.exit(1)

bloque = leer(client, 0x0000, 6)
client.close()

if bloque is None:
    print("No se pudo leer el bloque de registros. Revisa conexion/Work Mode del gateway.")
    sys.exit(1)

voltaje_raw = bloque[0]
corriente_raw = con_signo(bloque[2])
voltaje = voltaje_raw * 0.01

print(f"Voltaje: {voltaje:.2f} V  (crudo: {voltaje_raw})")
print(f"Corriente - valor CRUDO (sin escala): {corriente_raw}")
print()
print(f"Con factor 0.1  -> Corriente = {corriente_raw * 0.1:.2f} A  -> Potencia = {voltaje * corriente_raw * 0.1:.0f} W")
print(f"Con factor 0.01 -> Corriente = {corriente_raw * 0.01:.2f} A -> Potencia = {voltaje * corriente_raw * 0.01:.0f} W")
print()
print("Compara estos dos resultados contra la potencia REAL que muestra")
print("el MPPT/VRM en este momento, y usa el factor que mas se acerque.")
