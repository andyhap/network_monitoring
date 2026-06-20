import icmplib
from datetime import datetime
from models.database import get_active_devices
from utils.logger import get_logger
from utils import device_state, ws_client

logger = get_logger('ping_monitor')


def ping_device(device: dict, silent: bool = False) -> dict:
    """
    ICMP ping ke satu device, update device_state.
    silent=True menekan log per-device saat pause mode (kecuali UP).
    Return: dict hasil ping untuk dikirim ke server.
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


def run():
    if not ws_client.is_connected():
        logger.warning("=== Ping Monitor PAUSE — menunggu koneksi WS server ===")
        return

    was_all_down = device_state.all_down()

    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return

    if was_all_down:
        logger.warning("=== Ping Monitor (PAUSE) — cek recovery ===")
    else:
        logger.info("=== Ping Monitor mulai ===")

    results = []
    for device in devices:
        results.append(ping_device(device, silent=was_all_down))

    if device_state.all_down():
        if not was_all_down:
            logger.warning("=== SEMUA DEVICE DOWN — data tidak dikirim ke server ===")
        return

    if was_all_down:
        logger.info("=== Device kembali UP — monitoring RESUME ===")

    # Kirim semua hasil ping ke server via WebSocket
    collected_at = datetime.now().isoformat()
    for r in results:
        ws_client.send({
            'type':         'ping_result',
            'device':       r['name'],
            'ip_address':   r['ip'],
            'status':       r['status'],
            'latency_ms':   r['latency'],
            'packet_loss':  r['packet_loss'],
            'collected_at': collected_at,
        })
