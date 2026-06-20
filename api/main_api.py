import os
import paramiko
import icmplib
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.logger import get_logger
from models.database import get_session, DeviceStatus, Device, get_active_devices, SnmpMetric, InterfaceTraffic
from backup.supabase_backup import run as run_supabase_backup
import asyncio

load_dotenv()
logger = get_logger('api')

app = FastAPI(
    title="Network Monitoring API",
    description="API untuk monitoring jaringan — dynamic device management",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REBOOT_COMMANDS = {
    'mikrotik': '/system reboot',
    'openwrt':  'reboot',
    'linux':    'sudo reboot',
}


# ── Helper SSH ───────────────────────────────────────────────

def ssh_execute(host, user, password, command, timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host, username=user, password=password,
                       timeout=timeout, look_for_keys=False, allow_agent=False)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        return {'success': True, 'output': out, 'error': err}
    except paramiko.AuthenticationException:
        return {'success': False, 'output': '', 'error': 'Authentication failed'}
    except paramiko.ssh_exception.NoValidConnectionsError:
        return {'success': False, 'output': '', 'error': 'Cannot connect to host'}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}
    finally:
        client.close()


def get_device_or_404(name: str) -> Device:
    """Ambil device aktif dari DB, raise 404 jika tidak ada"""
    session = get_session()
    try:
        device = session.query(Device).filter(
            Device.name == name,
            Device.is_active == 1
        ).first()
        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"Device '{name}' tidak ditemukan atau nonaktif"
            )
        return {
            'name':      device.name,
            'ip':        device.ip_address,
            'type':      device.type,
            'ssh_user':  device.ssh_user,
            'ssh_pass':  device.ssh_pass,
        }
    finally:
        session.close()


# ── Pydantic Models ──────────────────────────────────────────

class PingRequest(BaseModel):
    device: str

class RebootRequest(BaseModel):
    device: str

class DeviceCreate(BaseModel):
    name:           str
    ip_address:     str
    type:           str
    ssh_user:       str = 'admin'
    ssh_pass:       str = ''
    snmp_community: str = 'public'
    description:    str = ''

class DeviceUpdate(BaseModel):
    ip_address:     Optional[str] = None
    type:           Optional[str] = None
    ssh_user:       Optional[str] = None
    ssh_pass:       Optional[str] = None
    snmp_community: Optional[str] = None
    description:    Optional[str] = None
    is_active:      Optional[int] = None


# ── Info Endpoints ───────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "Network Monitoring API",
        "version": "2.0.0",
        "status":  "running",
        "time":    datetime.now().isoformat()
    }

@app.get("/status")
def get_all_status():
    """Status terbaru semua device dari database"""
    from sqlalchemy import func
    session = get_session()
    try:
        subq = (
            session.query(
                DeviceStatus.device,
                func.max(DeviceStatus.id).label('max_id')
            ).group_by(DeviceStatus.device).subquery()
        )
        records = (
            session.query(DeviceStatus)
            .join(subq, DeviceStatus.id == subq.c.max_id)
            .all()
        )
        return {
            "status": "ok",
            "data": [{
                "device":     r.device,
                "ip_address": r.ip_address,
                "status":     r.status,
                "latency_ms": r.latency_ms,
                "checked_at": r.checked_at.isoformat(),
            } for r in records]
        }
    finally:
        session.close()

@app.get("/status/{device_name}")
def get_device_status(device_name: str):
    """Status terbaru satu device"""
    session = get_session()
    try:
        record = (
            session.query(DeviceStatus)
            .filter(DeviceStatus.device == device_name)
            .order_by(DeviceStatus.id.desc())
            .first()
        )
        if not record:
            raise HTTPException(status_code=404, detail="Belum ada data status")
        return {
            "status":     "ok",
            "device":     record.device,
            "ip_address": record.ip_address,
            "ping_status": record.status,
            "latency_ms": record.latency_ms,
            "checked_at": record.checked_at.isoformat(),
        }
    finally:
        session.close()


# ── Action Endpoints ─────────────────────────────────────────

@app.post("/ping")
def ping_now(req: PingRequest):
    """Ping manual ke device, simpan ke DB, return hasil"""
    device = get_device_or_404(req.device)
    ip     = device['ip']

    try:
        host    = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status  = 'up' if host.is_alive else 'down'
        latency = round(host.avg_rtt, 3) if host.is_alive else None
    except Exception as e:
        status, latency = 'down', None
        logger.error(f"Ping error {req.device}: {e}")

    session = get_session()
    try:
        session.add(DeviceStatus(
            device=req.device, ip_address=ip,
            status=status, latency_ms=latency,
            checked_at=datetime.now()
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error ping {req.device}: {e}")
    finally:
        session.close()

    logger.info(f"[API] Ping {req.device} ({ip}) — {status.upper()} | {latency} ms")
    return {
        "status":      "ok",
        "device":      req.device,
        "ip_address":  ip,
        "ping_result": status,
        "latency_ms":  latency,
        "checked_at":  datetime.now().isoformat(),
    }

@app.post("/reboot")
def reboot_device(req: RebootRequest):
    """Reboot device via SSH — credentials dari DB"""
    device = get_device_or_404(req.device)
    ip     = device['ip']
    user   = device['ssh_user']
    passwd = device['ssh_pass']
    cmd    = REBOOT_COMMANDS.get(device['type'], 'reboot')

    logger.info(f"[API] Reboot request: {req.device} ({ip})")
    result = ssh_execute(ip, user, passwd, cmd, timeout=10)

    if not result['success']:
        err = result['error']
        if not any(x in err for x in ['Connection reset', 'EOF', 'timed out']):
            logger.error(f"Reboot gagal {req.device}: {err}")
            raise HTTPException(status_code=500, detail=f"Reboot gagal: {err}")

    logger.info(f"[API] Reboot command terkirim ke {req.device}")
    return {
        "status":  "ok",
        "device":  req.device,
        "message": f"Reboot command berhasil dikirim ke {req.device}",
        "note":    "Device akan restart dalam beberapa detik",
        "sent_at": datetime.now().isoformat(),
    }


# ── Device CRUD Endpoints ────────────────────────────────────

@app.get("/api/devices")
def list_devices():
    """List semua device (aktif dan nonaktif)"""
    session = get_session()
    try:
        devices = session.query(Device).order_by(Device.id).all()
        return {
            "status": "ok",
            "data": [{
                "id":          d.id,
                "name":        d.name,
                "ip_address":  d.ip_address,
                "type":        d.type,
                "ssh_user":    d.ssh_user,
                "snmp_community": d.snmp_community,
                "is_active":   d.is_active,
                "description": d.description,
                "created_at":  d.created_at.isoformat(),
            } for d in devices]
        }
    finally:
        session.close()

@app.post("/api/devices")
def create_device(req: DeviceCreate):
    """Tambah device baru — langsung dimonitor pada siklus berikutnya"""
    session = get_session()
    try:
        existing = session.query(Device).filter(Device.name == req.name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Device '{req.name}' sudah ada")

        device = Device(
            name=req.name, ip_address=req.ip_address,
            type=req.type, ssh_user=req.ssh_user,
            ssh_pass=req.ssh_pass, snmp_community=req.snmp_community,
            description=req.description, is_active=1
        )
        session.add(device)
        session.commit()
        logger.info(f"[API] Device ditambahkan: {req.name} ({req.ip_address})")
        return {
            "status":  "ok",
            "message": f"Device '{req.name}' berhasil ditambahkan",
            "id":      device.id
        }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.put("/api/devices/{device_id}")
def update_device(device_id: int, req: DeviceUpdate):
    """Update detail device"""
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device tidak ditemukan")

        for field, value in req.dict(exclude_none=True).items():
            setattr(device, field, value)
        session.commit()
        logger.info(f"[API] Device diupdate: {device.name}")
        return {"status": "ok", "message": f"Device '{device.name}' berhasil diupdate"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.patch("/api/devices/{device_id}/toggle")
def toggle_device(device_id: int):
    """Toggle aktif/nonaktif device"""
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device tidak ditemukan")

        device.is_active = 0 if device.is_active == 1 else 1
        session.commit()
        status = "diaktifkan" if device.is_active == 1 else "dinonaktifkan"
        logger.info(f"[API] Device {device.name} {status}")
        return {
            "status":    "ok",
            "message":   f"Device '{device.name}' {status}",
            "is_active": device.is_active
        }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.delete("/api/devices/{device_id}")
def delete_device(device_id: int):
    """
    Hapus device permanen:
    1. Archive semua data monitoring ke Supabase (deleted_* tables)
    2. Hapus semua data monitoring dari DB lokal
    3. Hapus device dari tabel devices
    """
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device tidak ditemukan")

        name       = device.name
        ip_address = device.ip_address

        # Info device untuk disimpan sebagai metadata di archive
        device_info = {
            'id':             device.id,
            'name':           device.name,
            'ip_address':     device.ip_address,
            'type':           device.type,
            'ssh_user':       device.ssh_user,
            'snmp_community': device.snmp_community,
            'description':    device.description,
            'created_at':     device.created_at.isoformat(),
        }

        logger.info(f"[API] Mulai archive & hapus device: {name} ({ip_address})")

        # ── Step 1: Archive ke Supabase ──────────────────────
        try:
            from backup.supabase_backup import get_supabase_client
            client = get_supabase_client()
            now    = datetime.now().isoformat()

            # Archive device_status
            ds_records = session.query(DeviceStatus).filter(
                DeviceStatus.device == name
            ).all()
            if ds_records:
                client.table('deleted_device_status').insert([{
                    'device':      r.device,
                    'ip_address':  r.ip_address,
                    'status':      r.status,
                    'latency_ms':  r.latency_ms,
                    'checked_at':  r.checked_at.isoformat(),
                    'deleted_at':  now,
                    'device_info': device_info,
                } for r in ds_records]).execute()
                logger.info(f"[API] Archive {len(ds_records)} device_status records → Supabase")

            # Archive snmp_metrics
            sm_records = session.query(SnmpMetric).filter(
                SnmpMetric.device == name
            ).all()
            if sm_records:
                # Batch 500 agar tidak timeout
                for i in range(0, len(sm_records), 500):
                    batch = sm_records[i:i+500]
                    client.table('deleted_snmp_metrics').insert([{
                        'device':       r.device,
                        'ip_address':   r.ip_address,
                        'metric_name':  r.metric_name,
                        'metric_value': r.metric_value,
                        'collected_at': r.collected_at.isoformat(),
                        'deleted_at':   now,
                        'device_info':  device_info,
                    } for r in batch]).execute()
                logger.info(f"[API] Archive {len(sm_records)} snmp_metrics records → Supabase")

            # Archive interface_traffic
            it_records = session.query(InterfaceTraffic).filter(
                InterfaceTraffic.device == name
            ).all()
            if it_records:
                for i in range(0, len(it_records), 500):
                    batch = it_records[i:i+500]
                    client.table('deleted_interface_traffic').insert([{
                        'device':          r.device,
                        'ip_address':      r.ip_address,
                        'interface_name':  r.interface_name,
                        'bytes_in':        r.bytes_in,
                        'bytes_out':       r.bytes_out,
                        'packets_in':      r.packets_in,
                        'packets_out':     r.packets_out,
                        'collected_at':    r.collected_at.isoformat(),
                        'deleted_at':      now,
                        'device_info':     device_info,
                    } for r in batch]).execute()
                logger.info(f"[API] Archive {len(it_records)} interface_traffic records → Supabase")

        except Exception as e:
            logger.error(f"[API] Gagal archive ke Supabase: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal archive data ke Supabase sebelum hapus: {e}"
            )

        # ── Step 2: Hapus semua data monitoring dari lokal ───
        ds_deleted = session.query(DeviceStatus).filter(
            DeviceStatus.device == name
        ).delete()

        sm_deleted = session.query(SnmpMetric).filter(
            SnmpMetric.device == name
        ).delete()

        it_deleted = session.query(InterfaceTraffic).filter(
            InterfaceTraffic.device == name
        ).delete()

        # ── Step 3: Hapus device ─────────────────────────────
        session.delete(device)
        session.commit()

        logger.info(
            f"[API] Device '{name}' dihapus. "
            f"Data dihapus: {ds_deleted} status, "
            f"{sm_deleted} snmp, {it_deleted} traffic"
        )

        return {
            "status":  "ok",
            "message": f"Device '{name}' berhasil dihapus beserta semua datanya",
            "archived": {
                "device_status":     len(ds_records) if ds_records else 0,
                "snmp_metrics":      len(sm_records) if sm_records else 0,
                "interface_traffic": len(it_records) if it_records else 0,
            },
            "deleted_from_local": {
                "device_status":     ds_deleted,
                "snmp_metrics":      sm_deleted,
                "interface_traffic": it_deleted,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

# ── Backup Endpoints ─────────────────────────────────────────

async def execute_background_backup():
    try:
        logger.info("[API] Memulai proses backup manual ke Supabase...")
        # Panggil fungsi yang sudah di-import tadi
        await asyncio.to_thread(run_supabase_backup)
        logger.info("[API] Backup manual ke Supabase berhasil diselesaikan!")
    except Exception as e:
        logger.error(f"[API] Proses backup gagal di background: {str(e)}")

@app.post("/api/backup/manual")
def trigger_manual_backup(background_tasks: BackgroundTasks):
    """Memicu backup database manual ke Supabase via background task"""
    try:
        background_tasks.add_task(execute_background_backup)
        
        return {
            "status": "accepted",
            "message": "Backup akan dilakukan di background.",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[API] Gagal memicu endpoint backup: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kesalahan internal server saat memicu backup: {str(e)}"
        )


# ── WebSocket Server ─────────────────────────────────────────

WS_SECRET = os.getenv('WS_SECRET', '')


class ConnectionManager:
    def __init__(self):
        self._clients: List[WebSocket] = []
        self._last_data_at: Optional[datetime] = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        was_empty = len(self._clients) == 0
        self._clients.append(ws)
        if was_empty:
            logger.info(
                f"[WS] Client terhubung dari {ws.client.host} "
                f"— monitoring RESUME (data mulai diterima)"
            )
        else:
            logger.info(
                f"[WS] Client terhubung dari {ws.client.host} "
                f"— total: {len(self._clients)}"
            )

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)
        if len(self._clients) == 0:
            logger.warning(
                "[WS] Semua client terputus — monitoring PAUSE "
                "(tidak ada data yang masuk sampai client reconnect)"
            )
        else:
            logger.info(f"[WS] Client terputus — total: {len(self._clients)}")

    def record_data(self) -> None:
        """Dipanggil setiap kali data berhasil disimpan ke DB."""
        self._last_data_at = datetime.now()

    @property
    def count(self) -> int:
        return len(self._clients)

    @property
    def last_data_at(self) -> Optional[datetime]:
        return self._last_data_at


ws_manager = ConnectionManager()


def _ws_save_ping_result(payload: dict):
    """
    Terima hasil ping dari client dan simpan ke device_status + snmp_metrics(packet_loss).

    Format payload:
    {
        "type": "ping_result",
        "device": "main-router",
        "ip_address": "192.168.99.1",
        "status": "up",          # "up" | "down"
        "latency_ms": 1.234,     # null jika down
        "packet_loss": 0.0,      # 0.0 - 100.0
        "collected_at": "2026-06-20T10:00:00"  # opsional, default=now
    }
    """
    name        = payload['device']
    ip          = payload['ip_address']
    status      = payload['status']
    latency     = payload.get('latency_ms')
    packet_loss = payload.get('packet_loss', 100.0)
    collected_at_raw = payload.get('collected_at')
    collected_at = datetime.fromisoformat(collected_at_raw) if collected_at_raw else datetime.now()

    session = get_session()
    try:
        session.add(DeviceStatus(
            device=name, ip_address=ip,
            status=status, latency_ms=latency,
            checked_at=collected_at
        ))
        session.add(SnmpMetric(
            device=name, ip_address=ip,
            metric_name='packet_loss',
            metric_value=str(packet_loss),
            collected_at=collected_at
        ))
        session.commit()
        logger.info(f"[WS] ping_result: {name} {status.upper()} | {latency}ms | loss:{packet_loss}%")
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] DB error ping_result {name}: {e}")
        raise
    finally:
        session.close()


def _ws_save_snmp_metrics(payload: dict):
    """
    Terima raw SNMP metrics dari client dan simpan ke snmp_metrics.

    Format payload:
    {
        "type": "snmp_metrics",
        "device": "main-router",
        "ip_address": "192.168.99.1",
        "collected_at": "2026-06-20T10:00:00",
        "metrics": [
            {"name": "sysName",    "value": "MikroTik"},
            {"name": "sysUpTime",  "value": "1234567"},
            {"name": "macAddress", "value": "AA:BB:CC:DD:EE:FF"},
            ...
        ]
    }
    """
    name    = payload['device']
    ip      = payload['ip_address']
    metrics = payload.get('metrics', [])
    collected_at_raw = payload.get('collected_at')
    collected_at = datetime.fromisoformat(collected_at_raw) if collected_at_raw else datetime.now()

    session = get_session()
    try:
        for m in metrics:
            session.add(SnmpMetric(
                device=name, ip_address=ip,
                metric_name=m['name'],
                metric_value=str(m['value']),
                collected_at=collected_at
            ))
        session.commit()
        logger.info(f"[WS] snmp_metrics: {name} — {len(metrics)} metrics disimpan")
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] DB error snmp_metrics {name}: {e}")
        raise
    finally:
        session.close()


def _ws_save_interface_traffic(payload: dict):
    """
    Terima raw SNMP interface counters dari client dan simpan ke interface_traffic.

    Format payload:
    {
        "type": "interface_traffic",
        "device": "main-router",
        "ip_address": "192.168.99.1",
        "collected_at": "2026-06-20T10:00:00",
        "interfaces": [
            {
                "name": "ether1",
                "bytes_in": 1234567,
                "bytes_out": 2345678,
                "packets_in": 1234,
                "packets_out": 2345
            }
        ]
    }
    """
    name       = payload['device']
    ip         = payload['ip_address']
    interfaces = payload.get('interfaces', [])
    collected_at_raw = payload.get('collected_at')
    collected_at = datetime.fromisoformat(collected_at_raw) if collected_at_raw else datetime.now()

    session = get_session()
    try:
        for iface in interfaces:
            session.add(InterfaceTraffic(
                device=name, ip_address=ip,
                interface_name=iface['name'],
                bytes_in=iface.get('bytes_in', 0),
                bytes_out=iface.get('bytes_out', 0),
                packets_in=iface.get('packets_in', 0),
                packets_out=iface.get('packets_out', 0),
                collected_at=collected_at
            ))
        session.commit()
        logger.info(f"[WS] interface_traffic: {name} — {len(interfaces)} interface disimpan")
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] DB error interface_traffic {name}: {e}")
        raise
    finally:
        session.close()


_WS_HANDLERS = {
    'ping_result':       _ws_save_ping_result,
    'snmp_metrics':      _ws_save_snmp_metrics,
    'interface_traffic': _ws_save_interface_traffic,
}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, key: str = Query(default='')):
    """
    WebSocket endpoint untuk menerima data monitoring dari collector client.
    Autentikasi via query param: ws://<host>:<port>/ws?key=<WS_SECRET>
    Jika WS_SECRET kosong di .env, autentikasi dilewati.
    """
    if WS_SECRET and key != WS_SECRET:
        await websocket.close(code=4001, reason="Unauthorized")
        logger.warning(f"[WS] Koneksi ditolak dari {websocket.client.host} — key salah")
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            msg_type = payload.get('type')

            handler = _WS_HANDLERS.get(msg_type)
            if not handler:
                await websocket.send_json({
                    "status":  "error",
                    "type":    msg_type,
                    "message": f"Unknown type '{msg_type}'. Valid: {list(_WS_HANDLERS)}"
                })
                continue

            try:
                # Handler sinkron dijalankan di thread pool agar tidak blokir event loop
                await asyncio.to_thread(handler, payload)
                ws_manager.record_data()
                await websocket.send_json({"status": "ok", "type": msg_type})
            except KeyError as e:
                await websocket.send_json({
                    "status":  "error",
                    "type":    msg_type,
                    "message": f"Field wajib tidak ada: {e}"
                })
            except Exception as e:
                await websocket.send_json({
                    "status":  "error",
                    "type":    msg_type,
                    "message": str(e)
                })

    except WebSocketDisconnect:
        # Client menutup koneksi secara bersih
        ws_manager.disconnect(websocket)
    except Exception as e:
        # Koneksi putus tidak bersih (network error, timeout, dll)
        logger.error(f"[WS] Koneksi error dari {websocket.client.host}: {e}")
        ws_manager.disconnect(websocket)


@app.get("/ws/status")
def ws_status():
    """Info WebSocket server — status koneksi client dan kapan data terakhir diterima"""
    last = ws_manager.last_data_at
    return {
        "status":            "ok",
        "connected_clients": ws_manager.count,
        "monitoring_active": ws_manager.count > 0,
        "last_data_at":      last.isoformat() if last else None,
        "accepted_types":    list(_WS_HANDLERS),
        "auth_required":     bool(WS_SECRET),
    }