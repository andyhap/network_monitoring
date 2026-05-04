import icmplib
from datetime import datetime
from models.database import get_session, DeviceStatus, SnmpMetric, get_active_devices
from utils.logger import get_logger

logger = get_logger('ping_monitor')


def check_device(device: dict):
    name = device['name']
    ip   = device['ip_address']

    status      = 'down'
    latency     = None
    packet_loss = 100.0

    try:
        host        = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status      = 'up' if host.is_alive else 'down'
        latency     = round(host.avg_rtt, 3) if host.is_alive else None
        packet_loss = round(host.packet_loss * 100, 1)  # 0.0 - 100.0
        logger.info(f"{name} ({ip}) — {status.upper()} | latency: {latency} ms | loss: {packet_loss}%")
    except Exception as e:
        status, latency, packet_loss = 'down', None, 100.0
        logger.error(f"{name} ({ip}) — ERROR: {e}")

    now = datetime.now()
    session = get_session()
    try:
        # Simpan status ke device_status
        session.add(DeviceStatus(
            device=name, ip_address=ip,
            status=status, latency_ms=latency,
            checked_at=now
        ))

        # Simpan packetLoss ke snmp_metrics agar terbaca Laravel
        session.add(SnmpMetric(
            device=name, ip_address=ip,
            metric_name='packet_loss',
            metric_value=str(packet_loss),
            collected_at=now
        ))

        session.commit()
        logger.info(f"{name} — packet_loss {packet_loss}% tersimpan")
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