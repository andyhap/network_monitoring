import os
import icmplib
from datetime import datetime
from dotenv import load_dotenv
from models.database import get_session, DeviceStatus
from utils.logger import get_logger

load_dotenv()
logger = get_logger('ping_monitor')

DEVICES = {
    'main-router':    os.getenv('MAIN_ROUTER_IP'),
    'router-kantor':  os.getenv('ROUTER_KANTOR_IP'),
    'openwrt':        os.getenv('OPENWRT_IP'),
    'router-test':     os.getenv('ROUTER_TEST_IP'),
}

def check_device(name: str, ip: str):
    try:
        host = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=True)
        status    = 'up' if host.is_alive else 'down'
        latency   = round(host.avg_rtt, 3) if host.is_alive else None
        logger.info(f"{name} ({ip}) — {status.upper()} | latency: {latency} ms")
    except Exception as e:
        status, latency = 'down', None
        logger.error(f"{name} ({ip}) — ERROR: {e}")

    session = get_session()
    try:
        session.add(DeviceStatus(
            device=name, ip_address=ip,
            status=status, latency_ms=latency,
            checked_at=datetime.now()
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error saat simpan status {name}: {e}")
    finally:
        session.close()

def run():
    logger.info("=== Ping Monitor mulai ===")
    for name, ip in DEVICES.items():
        check_device(name, ip)