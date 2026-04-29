import os
from datetime import datetime
from easysnmp import Session, EasySNMPError
from dotenv import load_dotenv
from models.database import get_session, SnmpMetric
from utils.logger import get_logger

load_dotenv()
logger = get_logger('snmp_collector')

COMMUNITY = os.getenv('SNMP_COMMUNITY', 'public')
PORT      = int(os.getenv('SNMP_PORT', 161))

DEVICES = {
    'main-router':   os.getenv('MAIN_ROUTER_IP'),
    'router-kantor': os.getenv('ROUTER_KANTOR_IP'),
    'openwrt':       os.getenv('OPENWRT_IP'),
    'router-test':     os.getenv('ROUTER_TEST_IP'),
}

# OID yang akan dipoll
OIDS = {
    'sysName':        '1.3.6.1.2.1.1.5.0',
    'sysUpTime':      '1.3.6.1.2.1.1.3.0',
    'sysDescr':       '1.3.6.1.2.1.1.1.0',
    'sysContact':     '1.3.6.1.2.1.1.4.0',
    'sysLocation':    '1.3.6.1.2.1.1.6.0',
    'totalInterfaces':'1.3.6.1.2.1.2.1.0',
}

def poll_device(name: str, ip: str):
    try:
        session = Session(hostname=ip, community=COMMUNITY,
                          version=2, remote_port=PORT, timeout=5, retries=2)
        db_session = get_session()
        for metric_name, oid in OIDS.items():
            try:
                result = session.get(oid)
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
        logger.error(f"SNMP error pada {name} ({ip}): {e}")

def run():
    logger.info("=== SNMP Collector mulai ===")
    for name, ip in DEVICES.items():
        poll_device(name, ip)