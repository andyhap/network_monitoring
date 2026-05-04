import paramiko
import icmplib
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.logger import get_logger
from models.database import get_session, DeviceStatus, Device, get_active_devices

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
    """Hapus device permanen"""
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device tidak ditemukan")

        name = device.name
        session.delete(device)
        session.commit()
        logger.info(f"[API] Device dihapus: {name}")
        return {"status": "ok", "message": f"Device '{name}' berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()