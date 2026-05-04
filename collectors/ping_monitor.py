import icmplib
from datetime import datetime
from models.database import get_session, DeviceStatus, get_active_devices
from utils.logger import get_logger

logger = get_logger('ping_monitor')


def check_device(device: dict):
    name = device['name']
    ip   = device['ip_address']
    try:
        host    = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status  = 'up' if host.is_alive else 'down'
        latency = round(host.avg_rtt, 3) if host.is_alive else None
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
        logger.error(f"DB error ping {name}: {e}")
    finally:
        session.close()


def run():
    logger.info("=== Ping Monitor mulai ===")
    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return
    for device in devices:
        check_device(device)