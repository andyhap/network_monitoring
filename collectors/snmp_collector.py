import os
from datetime import datetime
from easysnmp import Session, EasySNMPError
from models.database import get_active_devices
from utils.logger import get_logger
from utils import device_state, ws_client

logger = get_logger('snmp_collector')

OIDS = {
    'sysName':         '1.3.6.1.2.1.1.5.0',
    'sysUpTime':       '1.3.6.1.2.1.1.3.0',
    'sysDescr':        '1.3.6.1.2.1.1.1.0',
    'sysContact':      '1.3.6.1.2.1.1.4.0',
    'sysLocation':     '1.3.6.1.2.1.1.6.0',
    'totalInterfaces': '1.3.6.1.2.1.2.1.0',
}

OID_IF_MAC = '1.3.6.1.2.1.2.2.1.6.2'  # ifPhysAddress index 2 (skip loopback)


def format_mac(raw_value: str) -> str:
    try:
        mac_bytes = [f"{ord(c):02X}" for c in raw_value]
        if len(mac_bytes) == 6:
            return ':'.join(mac_bytes)
    except Exception:
        pass
    return raw_value


def poll_device(device: dict) -> list:
    """
    Poll SNMP metrics dari satu device.
    Return list of {'name': ..., 'value': ...}, atau [] jika skip/gagal.
    """
    name      = device['name']
    ip        = device['ip_address']
    community = device['snmp_community']

    if not device_state.is_up(name):
        logger.warning(f"{name} ({ip}) — DOWN (ping), SNMP dilewati")
        return []

    metrics = []
    try:
        # timeout=2, retries=1 → maks 4s per OID
        snmp_session = Session(
            hostname=ip, community=community,
            version=2, remote_port=161, timeout=2, retries=1
        )

        for metric_name, oid in OIDS.items():
            try:
                result = snmp_session.get(oid)
                value  = str(result.value)
                logger.info(f"{name} | {metric_name}: {value}")
                metrics.append({'name': metric_name, 'value': value})
            except EasySNMPError as e:
                logger.warning(f"{name} | {metric_name} gagal: {e}")

        try:
            mac_result = snmp_session.get(OID_IF_MAC)
            mac_value  = format_mac(mac_result.value)
            logger.info(f"{name} | macAddress: {mac_value}")
            metrics.append({'name': 'macAddress', 'value': mac_value})
        except EasySNMPError as e:
            logger.warning(f"{name} | macAddress gagal: {e}")

        interval = os.getenv('PING_INTERVAL', '30')
        metrics.append({'name': 'monitoringInterval', 'value': f"{interval} Seconds"})

    except Exception as e:
        logger.error(f"SNMP error {name} ({ip}): {e}")

    return metrics


def run():
    if not ws_client.is_connected():
        logger.warning("=== SNMP Collector PAUSE — menunggu koneksi WS server ===")
        return

    if device_state.all_down():
        logger.warning("=== SNMP Collector PAUSE — semua device DOWN ===")
        return

    logger.info("=== SNMP Collector mulai ===")
    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return

    collected_at = datetime.now().isoformat()
    for device in devices:
        metrics = poll_device(device)
        if metrics:
            ws_client.send({
                'type':         'snmp_metrics',
                'device':       device['name'],
                'ip_address':   device['ip_address'],
                'collected_at': collected_at,
                'metrics':      metrics,
            })
