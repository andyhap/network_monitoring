"""
WebSocket client singleton untuk mengirim data monitoring ke server.

Desain:
- Kolektor memanggil ws_client.send(payload) secara sinkron (thread-safe).
- Payload masuk ke queue lalu dikirim oleh background sender loop.
- Receiver loop berjalan paralel — menerima command dari server (reboot/ping)
  dan mengirim hasilnya balik ke server.
- Jika koneksi putus, reconnect otomatis.
- Queue dibatasi 500 item; jika penuh, item terlama dibuang.
- is_connected() dipakai collector untuk pause/resume otomatis.
"""

import asyncio
import json
import queue
import time
import threading

import websockets

from utils.logger import get_logger

logger = get_logger('ws_client')

_queue: queue.Queue = queue.Queue(maxsize=500)
_connected: bool = False
_ws_url: str = ''

REBOOT_COMMANDS = {
    'mikrotik': '/system reboot',
    'openwrt':  'reboot',
    'linux':    'sudo reboot',
}


# ── Public API ────────────────────────────────────────────────

def start(server_url: str, secret: str = '') -> None:
    """Mulai background thread WebSocket client. Dipanggil sekali di main.py."""
    global _ws_url
    base = server_url.rstrip('/')
    _ws_url = base + '/ws' + (f'?key={secret}' if secret else '')

    threading.Thread(target=_run_event_loop, daemon=True).start()
    logger.info(f"[WS] Client thread dimulai → {_ws_url}")


def send(payload: dict) -> None:
    """Thread-safe: antri payload untuk dikirim ke server."""
    try:
        _queue.put_nowait(payload)
    except queue.Full:
        try:
            _queue.get_nowait()
        except queue.Empty:
            pass
        _queue.put_nowait(payload)


def is_connected() -> bool:
    return _connected


def wait_connected(timeout: float = 30) -> bool:
    """Block sampai terkoneksi atau timeout. Return True jika berhasil."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _connected:
            return True
        time.sleep(0.5)
    return False


# ── Internal ──────────────────────────────────────────────────

def _run_event_loop() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_connect_forever())


async def _connect_forever() -> None:
    global _connected
    was_connected = False
    retry_delay   = 5

    while True:
        try:
            async with websockets.connect(_ws_url, ping_interval=30) as ws:
                _connected    = True
                was_connected = True
                logger.info("[WS] Terhubung ke server — semua collector RESUME")
                await _drain_queue(ws)

        except Exception as e:
            _connected = False
            if was_connected:
                logger.warning(
                    f"[WS] Koneksi terputus — semua collector di-PAUSE. "
                    f"Retry dalam {retry_delay}s... ({e})"
                )
                was_connected = False
            else:
                logger.error(f"[WS] Gagal terhubung: {e}. Retry dalam {retry_delay}s...")

            await asyncio.sleep(retry_delay)


async def _drain_queue(ws) -> None:
    """Jalankan sender dan receiver secara bersamaan di satu koneksi."""
    await asyncio.gather(
        _sender_loop(ws),
        _receiver_loop(ws),
    )


async def _sender_loop(ws) -> None:
    """Ambil payload dari queue dan kirim ke server terus-menerus."""
    while True:
        try:
            payload = _queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.2)
            continue

        try:
            await ws.send(json.dumps(payload, default=str))
        except asyncio.CancelledError:
            # Kembalikan payload jika dibatalkan (receiver loop mati)
            try:
                _queue.put_nowait(payload)
            except queue.Full:
                pass
            raise
        except Exception as e:
            try:
                _queue.put_nowait(payload)
            except queue.Full:
                pass
            logger.error(f"[WS] Gagal kirim data: {e}")
            raise


async def _receiver_loop(ws) -> None:
    """Terima pesan dari server: ACK data diabaikan, command dieksekusi."""
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "command":
            # Jalankan sebagai task terpisah agar tidak blokir receiver
            asyncio.create_task(_handle_command(ws, msg))
        # else: {"status": "ok"} → ACK data, diabaikan


async def _handle_command(ws, cmd: dict) -> None:
    """Eksekusi command dari server, kirim hasilnya balik."""
    action     = cmd.get("action", "")
    request_id = cmd.get("request_id", "")

    logger.info(f"[WS] Command: {action} | device: {cmd.get('device')} ({cmd.get('ip')})")

    if action == "reboot":
        result = await asyncio.to_thread(
            _ssh_reboot,
            cmd.get("ip", ""),
            cmd.get("ssh_user", ""),
            cmd.get("ssh_pass", ""),
            cmd.get("device_type", ""),
        )
    elif action == "ping":
        result = await asyncio.to_thread(
            _icmp_ping,
            cmd.get("ip", ""),
        )
    else:
        result = {"success": False, "error": f"Unknown action: {action}"}

    try:
        await ws.send(json.dumps(
            {"type": "result", "request_id": request_id, **result},
            default=str
        ))
        logger.info(f"[WS] Result {action} terkirim → success={result.get('success')}")
    except Exception as e:
        logger.error(f"[WS] Gagal kirim result command: {e}")


def _ssh_reboot(ip: str, user: str, password: str, device_type: str) -> dict:
    """SSH ke device dan kirim perintah reboot."""
    import paramiko
    cmd    = REBOOT_COMMANDS.get(device_type, 'reboot')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ip, username=user, password=password,
            timeout=10, look_for_keys=False, allow_agent=False
        )
        stdin, stdout, stderr = client.exec_command(cmd, timeout=10)
        stdout.read()
        stderr.read()
        return {"success": True, "error": ""}
    except paramiko.AuthenticationException:
        return {"success": False, "error": "Authentication failed"}
    except Exception as e:
        err = str(e).lower()
        # Connection reset saat device reboot adalah normal
        if any(x in err for x in ['reset', 'eof', 'timed out', 'broken pipe']):
            return {"success": True, "error": ""}
        return {"success": False, "error": str(e)}
    finally:
        try:
            client.close()
        except Exception:
            pass


def _icmp_ping(ip: str) -> dict:
    """ICMP ping ke device, return status dan latency."""
    try:
        import icmplib
        host        = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status      = 'up' if host.is_alive else 'down'
        latency     = round(host.avg_rtt, 3) if host.is_alive else None
        packet_loss = round(host.packet_loss * 100, 1)
        return {"success": True, "status": status, "latency_ms": latency, "packet_loss": packet_loss}
    except Exception as e:
        return {"success": True, "status": "down", "latency_ms": None, "packet_loss": 100.0, "error": str(e)}
