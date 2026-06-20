"""
WebSocket client singleton untuk mengirim data monitoring ke server.

Desain:
- Kolektor memanggil ws_client.send(payload) secara sinkron (thread-safe).
- Payload masuk ke queue lalu dikirim oleh background thread via asyncio.
- Jika koneksi putus, reconnect otomatis. Payload yang gagal dikirim
  dikembalikan ke queue agar tidak hilang.
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
        # Buang item paling lama agar yang terbaru tetap masuk
        try:
            _queue.get_nowait()
        except queue.Empty:
            pass
        _queue.put_nowait(payload)


def is_connected() -> bool:
    return _connected


def wait_connected(timeout: float = 30) -> bool:
    """
    Block thread pemanggil sampai terkoneksi ke server atau timeout habis.
    Return True jika berhasil, False jika timeout.
    Dipanggil di main.py sebelum polling pertama dimulai.
    """
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
    was_connected = False  # track state sebelumnya agar log tidak berulang
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
                # Baru saja putus — log sekali sebagai WARNING
                logger.warning(
                    f"[WS] Koneksi terputus — semua collector di-PAUSE. "
                    f"Retry dalam {retry_delay}s... ({e})"
                )
                was_connected = False
            else:
                # Masih gagal sejak awal / retry — log ERROR tanpa spam
                logger.error(f"[WS] Gagal terhubung: {e}. Retry dalam {retry_delay}s...")

            await asyncio.sleep(retry_delay)


async def _drain_queue(ws) -> None:
    """Ambil payload dari queue dan kirim ke server satu per satu."""
    global _connected
    while True:
        # Cek antrian tanpa blokir
        try:
            payload = _queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.2)
            continue

        try:
            await ws.send(json.dumps(payload, default=str))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ack = json.loads(raw)
            if ack.get('status') != 'ok':
                logger.warning(f"[WS] Server error: {ack}")
        except Exception as e:
            # Kembalikan payload ke queue agar tidak hilang
            try:
                _queue.put_nowait(payload)
            except queue.Full:
                pass
            _connected = False
            logger.error(f"[WS] Gagal kirim: {e}")
            raise  # naik ke _connect_forever → trigger reconnect
