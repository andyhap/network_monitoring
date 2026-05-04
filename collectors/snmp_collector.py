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
        for metric_name, oid in OIDS.items():
            try:
                result = snmp_session.get(oid)
                value  = str(result.value)
                logger.info(f"{name} | {metric_name}: {value}")
                db_session.add(SnmpMetric(
                    device=name, ip_address=ip,
                    metric_name=metric_name, metric_value=value,
                    collected_at=datetime.now()
                ))
            except EasySNMPError as e:
                logger.warning(f"{name} | {metric_name} gagal: {e}")

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