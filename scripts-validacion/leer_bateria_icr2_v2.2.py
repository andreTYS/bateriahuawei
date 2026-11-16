#!/usr/bin/env python3
"""
Lector completo v2.2 - Bateria Huawei ESM-48150B1 (instalacion Icr 2 / Pizarro)
--------------------------------------------------------------------------------
Version de PC, alineada con el driver del Cerbo v2.2: mismo estilo de
lectura por bloques, mismos chequeos defensivos de longitud, para que
sirva de "espejo de validacion" - comparar en cualquier momento lo que
ve tu PC contra lo que muestra el panel del Cerbo.

NINGUN valor de lectura ni escala fue modificado respecto a versiones
anteriores - solo se agrego robustez (misma logica que el driver).

Configuracion:
  - Gateway: 192.168.1.27:8235 (Modbus Simple Protocol Conversion)
  - Direccion Modbus (slave/device id): 214

Uso:
    python leer_bateria_icr2_v2.2.py
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


def leer_bloque(client, addr, count, intentos=2):
    """Lee un bloque de registros consecutivos, con reintento + reconexion
    si hace falta. Devuelve (lista_de_registros, error_texto).
    Valida tambien que la cantidad de registros recibidos coincida con lo
    pedido - si el gateway devolviera un paquete truncado, se trata como
    fallo en vez de arriesgar un IndexError mas adelante."""
    ultimo_error = None
    for _ in range(intentos):
        try:
            try:
                res = client.read_holding_registers(address=addr, count=count, device_id=SLAVE_ID)
            except TypeError:
                try:
                    res = client.read_holding_registers(address=addr, count=count, slave=SLAVE_ID)
                except TypeError:
                    res = client.read_holding_registers(addr, count)
            if not res.isError():
                if len(res.registers) < count:
                    ultimo_error = f"paquete truncado ({len(res.registers)}/{count} registros)"
                else:
                    return res.registers, None
            else:
                ultimo_error = "ERROR de lectura"
        except Exception as e:
            ultimo_error = str(e)
            if not client.is_socket_open():
                client.close()
                time.sleep(0.5)
                client.connect()
        time.sleep(0.3)
    return None, ultimo_error


def con_signo(valor):
    if valor is None:
        return None
    return valor - 65536 if valor > 32767 else valor


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}.")
        print("Revisa: IP del gateway, Work Mode = TCP Server, cable en COM_IN.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}, esclavo {SLAVE_ID}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        while True:
            print("=" * 70)
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print("-" * 70)

            # --- Bloque 1: voltaje, voltaje_paquete, corriente, soc, soh, temp ---
            bloque1, error1 = leer_bloque(client, 0x0000, 6)

            voltaje = None
            if error1:
                print(f"{'Bloque 1 (datos basicos)':30s} -> ERROR: {error1}")
            else:
                voltaje = round(bloque1[0] * 0.01, 2)
                crudo_corriente = con_signo(bloque1[2])
                soc = bloque1[3]
                soh = bloque1[4]
                temp = con_signo(bloque1[5])

                print(f"{'Voltaje de Bateria':30s} -> {voltaje} V")
                print(f"{'Voltaje de Paquete':30s} -> {round(bloque1[1]*0.01,2)} V")
                print(f"{'SOC':30s} -> {soc} %")
                print(f"{'SOH':30s} -> {soh} %")
                print(f"{'Temp Maxima Celda':30s} -> {temp} C")

                print()
                print(f"{'Corriente (valor crudo)':30s} -> {crudo_corriente}")
                c01 = round(crudo_corriente * 0.1, 2)
                c001 = round(crudo_corriente * 0.01, 2)
                p01 = round((voltaje or 0) * c01)
                p001 = round((voltaje or 0) * c001)
                print(f"{'  con factor 0.1':30s} -> {c01} A  |  Potencia: {p01} W")
                print(f"{'  con factor 0.01':30s} -> {c001} A  |  Potencia: {p001} W")
                print("     (compara ambas potencias contra la real del MPPT/VRM)")

            print("-" * 70)

            # --- Bloque 2: limite_desc, (sin usar), limite_carga ---
            bloque2, error2 = leer_bloque(client, 0x100B, 3)
            if error2:
                print(f"{'Bloque 2 (limites)':30s} -> ERROR: {error2}")
            else:
                limite_desc = round(bloque2[0] * 0.1, 2)
                limite_carga = round(bloque2[2] * 0.1, 2)
                print(f"{'Limite Corriente Descarga':30s} -> {limite_desc} A")
                print(f"{'Limite Corriente Carga':30s} -> {limite_carga} A")

            # --- Bloque 3: fallos, (sin usar), protecciones, advertencias ---
            bloque3, error3 = leer_bloque(client, 0x0046, 4)
            if error3:
                print(f"{'Bloque 3 (fallos/protec.)':30s} -> ERROR: {error3}")
            else:
                fallos = bloque3[0]
                protecciones = bloque3[2]
                advertencias = bloque3[3]
                print(f"{'Fallos del Sistema':30s} -> 0x{fallos:04X} ({fallos:016b})")
                print(f"{'Protecciones Activas':30s} -> 0x{protecciones:04X} ({protecciones:016b})")
                print(f"{'Advertencias Activas':30s} -> 0x{advertencias:04X} ({advertencias:016b})")
                if protecciones != 0:
                    print("     *** HAY UNA PROTECCION ACTIVA - anota el valor y la hora ***")

            print()
            time.sleep(3)

    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()



def con_signo(valor):
    if valor is None:
        return None
    return valor - 65536 if valor > 32767 else valor


def main():
    client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=3)

    if not client.connect():
        print(f"No se pudo conectar a {GATEWAY_IP}:{GATEWAY_PORT}.")
        print("Revisa: IP del gateway, Work Mode = TCP Server, cable en COM_IN.")
        sys.exit(1)

    print(f"Conectado a {GATEWAY_IP}:{GATEWAY_PORT}, esclavo {SLAVE_ID}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        while True:
            print("=" * 70)
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print("-" * 70)

            # --- Bloque 1: voltaje, voltaje_paquete, corriente, soc, soh, temp ---
            bloque1, error1 = leer_bloque(client, 0x0000, 6)

            voltaje = None
            if error1:
                print(f"{'Bloque 1 (datos basicos)':30s} -> ERROR: {error1}")
            else:
                voltaje = round(bloque1[0] * 0.01, 2)
                crudo_corriente = con_signo(bloque1[2])
                soc = bloque1[3]
                soh = bloque1[4]
                temp = con_signo(bloque1[5])

                print(f"{'Voltaje de Bateria':30s} -> {voltaje} V")
                print(f"{'Voltaje de Paquete':30s} -> {round(bloque1[1]*0.01,2)} V")
                print(f"{'SOC':30s} -> {soc} %")
                print(f"{'SOH':30s} -> {soh} %")
                print(f"{'Temp Maxima Celda':30s} -> {temp} C")

                print()
                print(f"{'Corriente (valor crudo)':30s} -> {crudo_corriente}")
                c01 = round(crudo_corriente * 0.1, 2)
                c001 = round(crudo_corriente * 0.01, 2)
                p01 = round((voltaje or 0) * c01)
                p001 = round((voltaje or 0) * c001)
                print(f"{'  con factor 0.1':30s} -> {c01} A  |  Potencia: {p01} W")
                print(f"{'  con factor 0.01':30s} -> {c001} A  |  Potencia: {p001} W")
                print("     (compara ambas potencias contra la real del MPPT/VRM)")

            print("-" * 70)

            # --- Bloque 2: limite_desc, (sin usar), limite_carga ---
            bloque2, error2 = leer_bloque(client, 0x100B, 3)
            if error2:
                print(f"{'Bloque 2 (limites)':30s} -> ERROR: {error2}")
            else:
                limite_desc = round(bloque2[0] * 0.1, 2)
                limite_carga = round(bloque2[2] * 0.1, 2)
                print(f"{'Limite Corriente Descarga':30s} -> {limite_desc} A")
                print(f"{'Limite Corriente Carga':30s} -> {limite_carga} A")

            # --- Bloque 3: fallos, (sin usar), protecciones, advertencias ---
            bloque3, error3 = leer_bloque(client, 0x0046, 4)
            if error3:
                print(f"{'Bloque 3 (fallos/protec.)':30s} -> ERROR: {error3}")
            else:
                fallos = bloque3[0]
                protecciones = bloque3[2]
                advertencias = bloque3[3]
                print(f"{'Fallos del Sistema':30s} -> 0x{fallos:04X} ({fallos:016b})")
                print(f"{'Protecciones Activas':30s} -> 0x{protecciones:04X} ({protecciones:016b})")
                print(f"{'Advertencias Activas':30s} -> 0x{advertencias:04X} ({advertencias:016b})")
                if protecciones != 0:
                    print("     *** HAY UNA PROTECCION ACTIVA - anota el valor y la hora ***")

            print()
            time.sleep(3)

    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
