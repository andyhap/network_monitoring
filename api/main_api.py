import json
import uuid
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.logger import get_logger
from models.database import (
    get_session, DeviceStatus, Device, SnmpMetric, InterfaceTraffic,
)
from backup.supabase_backup import run as run_supabase_backup

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

# ── WebSocket state ───────────────────────────────────────────
# Hanya satu ws_client (monitoring machine lokal) yang terhubung
_active_ws: Optional[WebSocket] = None
_pending_commands: dict[str, asyncio.Future] = {}


# ── Pydantic Models ──────────────────────────────────────────

class PingRequest(BaseModel):
    device:    Optional[str] = None
    device_id: Optional[int] = None

class RebootRequest(BaseModel):
    device:    Optional[str] = None
    device_id: Optional[int] = None

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


# ── Helper DB ────────────────────────────────────────────────

def get_device_or_404(name: Optional[str] = None, device_id: Optional[int] = None) -> dict:
    """Ambil device aktif dari DB by name atau id, raise 404 jika tidak ada."""
    session = get_session()
    try:
        q = session.query(Device).filter(Device.is_active == 1)
        if device_id is not None:
            device = q.filter(Device.id == device_id).first()
            label  = f"id={device_id}"
        elif name:
            device = q.filter(Device.name == name).first()
            label  = f"'{name}'"
        else:
            raise HTTPException(status_code=422, detail="Harus isi 'device' atau 'device_id'")

        if not device:
            raise HTTPException(status_code=404, detail=f"Device {label} tidak ditemukan atau nonaktif")
        return {
            'name':     device.name,
            'ip':       device.ip_address,
            'type':     device.type,
            'ssh_user': device.ssh_user,
            'ssh_pass': device.ssh_pass,
        }
    finally:
        session.close()


# ── WS endpoint ──────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    global _active_ws
    await websocket.accept()
    _active_ws = websocket
    logger.info("[WS] ws_client terhubung dari monitoring machine")

    try:
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "result":
                # Hasil command (reboot/ping) dari ws_client
                req_id = msg.get("request_id", "")
                fut    = _pending_commands.get(req_id)
                if fut and not fut.done():
                    fut.set_result(msg)

            elif msg_type == "ping_result":
                await asyncio.to_thread(_save_ping_result, msg)
                await websocket.send_text('{"status":"ok"}')

            elif msg_type == "snmp_metrics":
                await asyncio.to_thread(_save_snmp_metrics, msg)
                await websocket.send_text('{"status":"ok"}')

            elif msg_type == "interface_traffic":
                await asyncio.to_thread(_save_interface_traffic, msg)
                await websocket.send_text('{"status":"ok"}')

            else:
                await websocket.send_text('{"status":"ok"}')

    except WebSocketDisconnect:
        logger.warning("[WS] ws_client terputus")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        _active_ws = None
        for fut in _pending_commands.values():
            if not fut.done():
                fut.cancel()
        _pending_commands.clear()


# ── WS data savers ───────────────────────────────────────────

def _save_ping_result(msg: dict) -> None:
    session = get_session()
    try:
        ts = datetime.fromisoformat(msg['collected_at']) if msg.get('collected_at') else datetime.now()
        session.add(DeviceStatus(
            device=msg['device'], ip_address=msg['ip_address'],
            status=msg['status'], latency_ms=msg.get('latency_ms'),
            checked_at=ts,
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] Gagal simpan ping_result: {e}")
    finally:
        session.close()


def _save_snmp_metrics(msg: dict) -> None:
    session = get_session()
    try:
        ts = datetime.fromisoformat(msg['collected_at']) if msg.get('collected_at') else datetime.now()
        for m in msg.get('metrics', []):
            session.add(SnmpMetric(
                device=msg['device'], ip_address=msg['ip_address'],
                metric_name=m['name'], metric_value=str(m['value']),
                collected_at=ts,
            ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] Gagal simpan snmp_metrics: {e}")
    finally:
        session.close()


def _save_interface_traffic(msg: dict) -> None:
    session = get_session()
    try:
        ts = datetime.fromisoformat(msg['collected_at']) if msg.get('collected_at') else datetime.now()
        for iface in msg.get('interfaces', []):
            session.add(InterfaceTraffic(
                device=msg['device'], ip_address=msg['ip_address'],
                interface_name=iface['name'],
                bytes_in=iface.get('bytes_in', 0),
                bytes_out=iface.get('bytes_out', 0),
                packets_in=iface.get('packets_in', 0),
                packets_out=iface.get('packets_out', 0),
                collected_at=ts,
            ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"[WS] Gagal simpan interface_traffic: {e}")
    finally:
        session.close()


# ── WS command sender ────────────────────────────────────────

async def _send_command(cmd: dict, timeout: float = 30) -> dict:
    """Kirim command ke ws_client lewat WS, tunggu hasilnya."""
    if _active_ws is None:
        raise HTTPException(503, detail="ws_client tidak terhubung ke server")

    request_id             = str(uuid.uuid4())
    cmd["request_id"]      = request_id
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending_commands[request_id] = future

    try:
        await _active_ws.send_text(json.dumps(cmd, default=str))
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(504, detail="Timeout — ws_client tidak merespons dalam 30 detik")
    finally:
        _pending_commands.pop(request_id, None)


# ── Info Endpoints ───────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service":    "Network Monitoring API",
        "version":    "2.0.0",
        "status":     "running",
        "ws_client":  "connected" if _active_ws else "disconnected",
        "time":       datetime.now().isoformat()
    }

@app.get("/status")
def get_all_status():
    """Status terbaru semua device dari database."""
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
    """Status terbaru satu device."""
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
            "status":      "ok",
            "device":      record.device,
            "ip_address":  record.ip_address,
            "ping_status": record.status,
            "latency_ms":  record.latency_ms,
            "checked_at":  record.checked_at.isoformat(),
        }
    finally:
        session.close()


# ── Action Endpoints ─────────────────────────────────────────

@app.post("/ping")
async def ping_now(req: PingRequest):
    """Ping manual ke device via ws_client (lokal), simpan ke DB."""
    device = get_device_or_404(req.device, req.device_id)
    ip     = device['ip']

    result      = await _send_command({"type": "command", "action": "ping", "device": device['name'], "ip": ip})
    status      = result.get('status', 'down')
    latency     = result.get('latency_ms')
    packet_loss = result.get('packet_loss')

    session = get_session()
    try:
        session.add(DeviceStatus(
            device=device['name'], ip_address=ip,
            status=status, latency_ms=latency,
            checked_at=datetime.now()
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error ping {device['name']}: {e}")
    finally:
        session.close()

    logger.info(f"[API] Ping {device['name']} ({ip}) — {status.upper()} | {latency} ms")
    return {
        "status":       "ok",
        "device":       device['name'],
        "ip_address":   ip,
        "ping_result":  status,
        "latency_ms":   latency,
        "packet_loss":  packet_loss,
        "checked_at":   datetime.now().isoformat(),
    }

@app.post("/reboot")
async def reboot_device(req: RebootRequest):
    """Reboot device via ws_client (SSH dari lokal) — credentials dari DB."""
    device = get_device_or_404(req.device, req.device_id)

    logger.info(f"[API] Reboot request: {device['name']} ({device['ip']})")
    result = await _send_command({
        "type":        "command",
        "action":      "reboot",
        "device":      device['name'],
        "ip":          device['ip'],
        "device_type": device['type'],
        "ssh_user":    device['ssh_user'],
        "ssh_pass":    device['ssh_pass'],
    })

    if not result.get("success"):
        err = result.get("error", "Unknown error")
        logger.error(f"[API] Reboot gagal {device['name']}: {err}")
        raise HTTPException(status_code=500, detail=f"Reboot gagal: {err}")

    logger.info(f"[API] Reboot berhasil: {device['name']}")
    return {
        "status":  "ok",
        "device":  device['name'],
        "message": f"Reboot command berhasil dikirim ke {device['name']}",
        "note":    "Device akan restart dalam beberapa detik",
        "sent_at": datetime.now().isoformat(),
    }


# ── Device CRUD Endpoints ────────────────────────────────────

@app.get("/api/devices")
def list_devices():
    """List semua device (aktif dan nonaktif)."""
    session = get_session()
    try:
        devices = session.query(Device).order_by(Device.id).all()
        return {
            "status": "ok",
            "data": [{
                "id":             d.id,
                "name":           d.name,
                "ip_address":     d.ip_address,
                "type":           d.type,
                "ssh_user":       d.ssh_user,
                "snmp_community": d.snmp_community,
                "is_active":      d.is_active,
                "description":    d.description,
                "created_at":     d.created_at.isoformat(),
            } for d in devices]
        }
    finally:
        session.close()

@app.post("/api/devices")
def create_device(req: DeviceCreate):
    """Tambah device baru — langsung dimonitor pada siklus berikutnya."""
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
    """Update detail device."""
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device tidak ditemukan")

        for field, value in req.model_dump(exclude_none=True).items():
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
    """Toggle aktif/nonaktif device."""
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

            ds_records = session.query(DeviceStatus).filter(DeviceStatus.device == name).all()
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

            sm_records = session.query(SnmpMetric).filter(SnmpMetric.device == name).all()
            if sm_records:
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

            it_records = session.query(InterfaceTraffic).filter(InterfaceTraffic.device == name).all()
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

        # ── Step 2 & 3: Hapus dari lokal ─────────────────────
        ds_deleted = session.query(DeviceStatus).filter(DeviceStatus.device == name).delete()
        sm_deleted = session.query(SnmpMetric).filter(SnmpMetric.device == name).delete()
        it_deleted = session.query(InterfaceTraffic).filter(InterfaceTraffic.device == name).delete()
        session.delete(device)
        session.commit()

        logger.info(
            f"[API] Device '{name}' dihapus. "
            f"Data: {ds_deleted} status, {sm_deleted} snmp, {it_deleted} traffic"
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
        await asyncio.to_thread(run_supabase_backup)
        logger.info("[API] Backup manual ke Supabase berhasil diselesaikan!")
    except Exception as e:
        logger.error(f"[API] Proses backup gagal di background: {str(e)}")

@app.post("/api/backup/manual")
def trigger_manual_backup(background_tasks: BackgroundTasks):
    """Memicu backup database manual ke Supabase via background task."""
    try:
        background_tasks.add_task(execute_background_backup)
        return {
            "status":    "accepted",
            "message":   "Backup akan dilakukan di background.",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[API] Gagal memicu endpoint backup: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kesalahan internal server saat memicu backup: {str(e)}"
        )
