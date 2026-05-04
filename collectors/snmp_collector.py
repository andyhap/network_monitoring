from datetime import datetime
from easysnmp import Session, EasySNMPError
from models.database import get_session, SnmpMetric, get_active_devices
from utils.logger import get_logger

logger = get_logger('snmp_collector')

OIDS = {
    'sysName':         '1.3.6.1.2.1.1.5.0',
    'sysUpTime':       '1.3.6.1.2.1.1.3.0',
    'sysDescr':        '1.3.6.1.2.1.1.1.0',
    'sysContact':      '1.3.6.1.2.1.1.4.0',
    'sysLocation':     '1.3.6.1.2.1.1.6.0',
    'totalInterfaces': '1.3.6.1.2.1.2.1.0',
}

# OID MAC address interface pertama (biasanya ether1/eth0)
OID_IF_MAC = '1.3.6.1.2.1.2.2.1.6.2'  # ifPhysAddress index 2 (skip loopback)


def format_mac(raw_value: str) -> str:
    """Konversi raw bytes MAC address ke format XX:XX:XX:XX:XX:XX"""
    try:
        # easysnmp return MAC sebagai string bytes
        mac_bytes = [f"{ord(c):02X}" for c in raw_value]
        if len(mac_bytes) == 6:
            return ':'.join(mac_bytes)
    except Exception:
        pass
    return raw_value


def poll_device(device: dict):
    name      = device['name']
    ip        = device['ip_address']
    community = device['snmp_community']

    try:
        snmp_session = Session(
            hostname=ip, community=community,
            version=2, remote_port=161, timeout=5, retries=2
        )
        db_session = get_session()
        now = datetime.now()

        # Poll OID standar
        for metric_name, oid in OIDS.items():
            try:
                result = snmp_session.get(oid)
                value  = str(result.value)
                logger.info(f"{name} | {metric_name}: {value}")
                db_session.add(SnmpMetric(
                    device=name, ip_address=ip,
                    metric_name=metric_name, metric_value=value,
                    collected_at=now
                ))
            except EasySNMPError as e:
                logger.warning(f"{name} | {metric_name} gagal: {e}")

        # Poll MAC address
        try:
            mac_result = snmp_session.get(OID_IF_MAC)
            mac_value  = format_mac(mac_result.value)
            logger.info(f"{name} | macAddress: {mac_value}")
            db_session.add(SnmpMetric(
                device=name, ip_address=ip,
                metric_name='macAddress',
                metric_value=mac_value,
                collected_at=now
            ))
        except EasySNMPError as e:
            logger.warning(f"{name} | macAddress gagal: {e}")

        # Simpan monitoringInterval (dari .env / config)
        import os
        interval = os.getenv('PING_INTERVAL', '30')
        db_session.add(SnmpMetric(
            device=name, ip_address=ip,
            metric_name='monitoringInterval',
            metric_value=f"{interval} Seconds",
            collected_at=now
        ))

        db_session.commit()
        db_session.close()
    except Exception as e:
        logger.error(f"SNMP error {name} ({ip}): {e}")


def run():
    logger.info("=== SNMP Collector mulai ===")
    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return
    for device in devices:
        poll_device(device)