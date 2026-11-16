#!/usr/bin/env python3
"""
Lee el valor CRUDO (sin ninguna escala aplicada) del registro de corriente
y voltaje de la bateria Huawei, para calcular el factor de escala real
comparando contra la potencia/corriente real conocida (ej. la que reporta
el MPPT o un medidor externo).

Ajusta GATEWAY_IP, GATEWAY_PORT y SLAVE_ID a los de la instalacion actual
(Pizarro / Icr 2) antes de correr.
"""

import sys
from pymodbus.client import ModbusTcpClient

# ---------- AJUSTA ESTO a los datos de la instalacion Icr 2 ----------
GATEWAY_IP = "192.168.1.27"   # IP del gateway en esta ubicacion
GATEWAY_PORT = 8235
SLAVE_ID = 214
# -----------------------------------------------------------------------

def leer(client, addr):
    try:
        r = client.read_holding_registers(address=addr, count=1, device_id=SLAVE_ID)
    except TypeError:
        try:
            r = client.read_holding_registers(address=addr, count=1, slave=SLAVE_ID)
        except TypeError:
            r = client.read_holding_registers(addr, 1)
    if r.isError():
        return None
    return r.registers[0]

def con_signo(v):
    if v is None:
        return None
    return v - 65536 if v > 32767 else v

client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)
if not client.connect():
    print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}")
    sys.exit(1)

voltaje_raw = leer(client, 0x0000)
corriente_raw = con_signo(leer(client, 0x0002))

print(f"Voltaje - valor crudo: {voltaje_raw}  (con factor 0.01 -> {voltaje_raw * 0.01 if voltaje_raw else '?'} V)")
print(f"Corriente - valor crudo: {corriente_raw}")
print()
print("Con este valor crudo de corriente, y sabiendo la potencia REAL")
print("actual (ej. la que reporta el MPPT en watts), calcula el factor:")
print("  factor_real = corriente_real_en_amperios / valor_crudo")
print("  donde corriente_real_en_amperios = potencia_real_W / voltaje_V")

client.close()
