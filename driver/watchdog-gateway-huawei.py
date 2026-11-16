#!/usr/bin/env python3
"""
watchdog-gateway-huawei
-------------------------
Monitorea la conectividad Modbus TCP hacia el gateway RS485-Ethernet cada
cierto tiempo, y deja un registro claro de caidas prolongadas - util para
detectar cuando el gateway "olvido" su configuracion de Work Mode = TCP
Server tras un corte de energia (el sintoma es: conecta al puerto TCP
pero la bateria no responde, o el puerto ni siquiera acepta conexion).

LIMITACION IMPORTANTE (honesta): este script NO reconfigura el gateway
automaticamente. No tenemos documentado con certeza el endpoint/formulario
que usa su interfaz web para escribir la configuracion (solo sabemos como
se ve navegando manualmente), y enviar peticiones a ciegas a un endpoint
no confirmado podria escribir datos incorrectos sin que te des cuenta.
Este script se limita a DETECTAR y DEJAR CONSTANCIA de forma confiable,
para que la correccion manual (revisar Work Mode en la interfaz web) sea
mas rapida de decidir cuando hace falta.

Instalacion: igual que el driver principal, como servicio independiente
en /data/watchdog-gateway-huawei/service/
"""

import socket
import time
import json
import logging
from datetime import datetime, timezone

# ---------------- CONFIGURACION ----------------
GATEWAY_IP = "192.168.1.27"
GATEWAY_PORT = 8235
CHECK_INTERVAL_S = 60          # cada cuanto revisa
TIMEOUT_S = 5                  # timeout de cada intento de conexion
ARCHIVO_ESTADO = "/data/watchdog-gateway-huawei/estado.json"
UMBRAL_ALERTA_MINUTOS = 5      # si lleva mas de esto caido, marca alerta
# -------------------------------------------------

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("watchdog-gateway")


def probar_conexion_tcp(ip, puerto, timeout):
    """Intenta abrir un socket TCP simple al gateway. No habla Modbus,
    solo confirma si el puerto esta escuchando (equivalente a lo que
    hace Test-NetConnection en PowerShell)."""
    try:
        with socket.create_connection((ip, puerto), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def cargar_estado():
    try:
        with open(ARCHIVO_ESTADO, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'ultima_caida_desde': None, 'caido_actualmente': False}


def guardar_estado(estado):
    with open(ARCHIVO_ESTADO, 'w') as f:
        json.dump(estado, f, indent=2)


def main():
    log.info(f"Watchdog iniciado - monitoreando {GATEWAY_IP}:{GATEWAY_PORT} "
              f"cada {CHECK_INTERVAL_S}s")

    estado = cargar_estado()

    while True:
        ok = probar_conexion_tcp(GATEWAY_IP, GATEWAY_PORT, TIMEOUT_S)
        ahora = datetime.now(timezone.utc).isoformat()

        if ok:
            if estado['caido_actualmente']:
                log.info(f"Gateway RECUPERADO ({ahora}). Estaba caido desde "
                          f"{estado['ultima_caida_desde']}")
            estado['caido_actualmente'] = False
            estado['ultima_caida_desde'] = None
            estado['ultima_verificacion_ok'] = ahora
        else:
            if not estado['caido_actualmente']:
                log.warning(f"Gateway SIN RESPUESTA en {GATEWAY_IP}:{GATEWAY_PORT} "
                            f"desde {ahora}")
                estado['ultima_caida_desde'] = ahora
                estado['caido_actualmente'] = True
            else:
                # Calcula hace cuanto esta caido
                try:
                    desde = datetime.fromisoformat(estado['ultima_caida_desde'])
                    minutos_caido = (datetime.now(timezone.utc) - desde).total_seconds() / 60
                    if minutos_caido >= UMBRAL_ALERTA_MINUTOS:
                        log.error(
                            f"ALERTA: gateway lleva {minutos_caido:.0f} minutos sin "
                            f"responder. Revisa manualmente http://{GATEWAY_IP} -> "
                            f"Port Parameter -> Work Mode debe ser 'TCP Server'."
                        )
                except (KeyError, ValueError):
                    pass

        guardar_estado(estado)
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    main()

"""
--------------------------------------------------------------------------
INSTALACION (via SSH, independiente del driver principal):
--------------------------------------------------------------------------
1. Crear estructura:
     mkdir -p /data/watchdog-gateway-huawei/service/log

2. Subir este archivo (desde una ventana NUEVA de PowerShell, sin SSH):
     scp "C:\\ruta\\watchdog-gateway-huawei.py" root@192.168.1.22:/data/watchdog-gateway-huawei/

3. Dar permisos:
     chmod +x /data/watchdog-gateway-huawei/watchdog-gateway-huawei.py

4. Crear el servicio:
     cat > /data/watchdog-gateway-huawei/service/run << 'EOF'
     #!/bin/sh
     exec python3 /data/watchdog-gateway-huawei/watchdog-gateway-huawei.py
     EOF
     chmod +x /data/watchdog-gateway-huawei/service/run

     cat > /data/watchdog-gateway-huawei/service/log/run << 'EOF'
     #!/bin/sh
     exec svlogd -tt /data/watchdog-gateway-huawei/log
     EOF
     chmod +x /data/watchdog-gateway-huawei/service/log/run
     mkdir -p /data/watchdog-gateway-huawei/log

5. Activar:
     ln -s /data/watchdog-gateway-huawei/service /service/watchdog-gateway-huawei
     echo 'ln -s /data/watchdog-gateway-huawei/service /service/watchdog-gateway-huawei' >> /data/rc.local

6. Verificar:
     svstat /service/watchdog-gateway-huawei
     cat /data/watchdog-gateway-huawei/estado.json
--------------------------------------------------------------------------
"""
