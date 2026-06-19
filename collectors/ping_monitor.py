import icmplib
from datetime import datetime
from models.database import get_session, DeviceStatus, SnmpMetric, get_active_devices
from utils.logger import get_logger
from utils import device_state

logger = get_logger('ping_monitor')


def ping_device(device: dict, silent: bool = False) -> dict:
    """
    Hanya ICMP ping dan update device_state. Tidak menulis ke DB.
    silent=True menekan log per-device saat pause mode (kecuali UP).
    Return: dict hasil ping untuk di-batch-save nanti.
    """
    name = device['name']
    ip   = device['ip_address']

    status      = 'down'
    latency     = None
    packet_loss = 100.0

    try:
        host        = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status      = 'up' if host.is_alive else 'down'
        latency     = round(host.avg_rtt, 3) if host.is_alive else None
        packet_loss = round(host.packet_loss * 100, 1)
        if not silent or status == 'up':
            logger.info(f"{name} ({ip}) — {status.upper()} | latency: {latency} ms | loss: {packet_loss}%")
    except Exception as e:
        status, latency, packet_loss = 'down', None, 100.0
        if not silent:
            logger.error(f"{name} ({ip}) — ERROR: {e}")

    device_state.update(name, status == 'up')
    return {'name': name, 'ip': ip, 'status': status,
            'latency': latency, 'packet_loss': packet_loss}


def _save_to_db(results: list):
    """Simpan batch hasil ping ke database (device_status + packet_loss di snmp_metrics)."""
    now     = datetime.now()
    session = get_session()
    try:
        for r in results:
            session.add(DeviceStatus(
                device=r['name'], ip_address=r['ip'],
                status=r['status'], latency_ms=r['latency'],
                checked_at=now
            ))
            session.add(SnmpMetric(
                device=r['name'], ip_address=r['ip'],
                metric_name='packet_loss',
                metric_value=str(r['packet_loss']),
                collected_at=now
            ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error saat simpan ping results: {e}")
    finally:
        session.close()


def run():
    was_all_down = device_state.all_down()

    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return

    if was_all_down:
        # Sudah dalam mode pause — log satu baris saja, suppress per-device
        logger.warning("=== Ping Monitor (PAUSE) — cek recovery ===")
    else:
        logger.info("=== Ping Monitor mulai ===")

    # Kumpulkan hasil ping dulu, baru putuskan apakah perlu tulis ke DB
    results = []
    for device in devices:
        results.append(ping_device(device, silent=was_all_down))

    if device_state.all_down():
        if not was_all_down:
            # Baru saja masuk pause mode — catat satu kali
            logger.warning("=== SEMUA DEVICE DOWN — monitoring di-PAUSE, tidak ada data ditulis ke DB ===")
        # Tidak tulis apapun ke DB
        return

    # Ada device yang UP → tulis semua hasil ke DB
    if was_all_down:
        logger.info("=== Device kembali UP — monitoring RESUME ===")

    _save_to_db(results)