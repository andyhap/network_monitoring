import os
import paramiko
import icmplib
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.logger import get_logger
from models.database import get_session, DeviceStatus

load_dotenv()
logger = get_logger('api')

app = FastAPI(
    title="Network Monitoring API",
    description="API untuk monitoring jaringan — reboot device & ping",
    version="1.0.0"
)

# CORS agar Laravel bisa akses
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Konfigurasi device ───────────────────────────────────────
DEVICES = {
    'main-router': {
        'ip':       os.getenv('MAIN_ROUTER_IP'),
        'mgmt_ip':  os.getenv('MAIN_ROUTER_IP'),
        'ssh_user': os.getenv('MAIN_ROUTER_SSH_USER', 'admin'),
        'ssh_pass': os.getenv('MAIN_ROUTER_SSH_PASS', ''),
        'type':     'mikrotik',
    },
    'router-kantor': {
        'ip':       os.getenv('ROUTER_KANTOR_IP'),
        'mgmt_ip':  os.getenv('ROUTER_KANTOR_IP'),
        'ssh_user': os.getenv('ROUTER_KANTOR_SSH_USER', 'admin'),
        'ssh_pass': os.getenv('ROUTER_KANTOR_SSH_PASS', ''),
        'type':     'mikrotik',
    },
    'openwrt': {
        'ip':       os.getenv('OPENWRT_IP'),
        'mgmt_ip':  os.getenv('OPENWRT_IP'),
        'ssh_user': os.getenv('OPENWRT_SSH_USER', 'root'),
        'ssh_pass': os.getenv('OPENWRT_SSH_PASS', ''),
        'type':     'openwrt',
    },
        'router-test': {
        'ip':       os.getenv('ROUTER_TEST_IP'),
        'mgmt_ip':  os.getenv('ROUTER_TEST_IP'),
        'ssh_user': os.getenv('ROUTER_TEST_SSH_USER', 'admin'),
        'ssh_pass': os.getenv('ROUTER_TEST_SSH_PASS', ''),
        'type':     'mikrotik',
    },
}

# Reboot command per device type
REBOOT_COMMANDS = {
    'mikrotik': '/system reboot',
    'openwrt':  'reboot',
}

# ── Helper SSH ───────────────────────────────────────────────

def ssh_execute(host: str, user: str, password: str, command: str, timeout: int = 10) -> dict:
    """Eksekusi command via SSH, return output dan status"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            username=user,
            password=password,
            timeout=timeout,
            look_for_keys=False,
            allow_agent=False
        )
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

# ── Models ───────────────────────────────────────────────────

class RebootRequest(BaseModel):
    device: str  # main-router / router-kantor / openwrt

class PingRequest(BaseModel):
    device: str  # main-router / router-kantor / openwrt

# ── Endpoints ────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "Network Monitoring API",
        "status":  "running",
        "time":    datetime.now().isoformat()
    }

@app.get("/devices")
def list_devices():
    """Daftar semua device yang terdaftar"""
    return {
        "devices": [
            {"name": name, "ip": cfg["mgmt_ip"], "type": cfg["type"]}
            for name, cfg in DEVICES.items()
        ]
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
            "data": [
                {
                    "device":     r.device,
                    "ip_address": r.ip_address,
                    "status":     r.status,
                    "latency_ms": r.latency_ms,
                    "checked_at": r.checked_at.isoformat(),
                }
                for r in records
            ]
        }
    finally:
        session.close()

@app.get("/status/{device_name}")
def get_device_status(device_name: str):
    """Status terbaru satu device"""
    if device_name not in DEVICES:
        raise HTTPException(status_code=404, detail=f"Device '{device_name}' tidak ditemukan")

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
            "status":     record.status,
            "latency_ms": record.latency_ms,
            "checked_at": record.checked_at.isoformat(),
        }
    finally:
        session.close()

@app.post("/ping")
def ping_now(req: PingRequest):
    """
    Trigger ping manual ke device tertentu.
    Simpan hasilnya ke DB dan return langsung ke Laravel.
    """
    if req.device not in DEVICES:
        raise HTTPException(status_code=404, detail=f"Device '{req.device}' tidak ditemukan")

    cfg = DEVICES[req.device]
    ip  = cfg['mgmt_ip']

    try:
        host    = icmplib.ping(ip, count=4, interval=0.5, timeout=2, privileged=False)
        status  = 'up' if host.is_alive else 'down'
        latency = round(host.avg_rtt, 3) if host.is_alive else None
    except Exception as e:
        status, latency = 'down', None
        logger.error(f"Ping error {req.device}: {e}")

    # Simpan ke DB
    session = get_session()
    try:
        session.add(DeviceStatus(
            device=req.device,
            ip_address=ip,
            status=status,
            latency_ms=latency,
            checked_at=datetime.now()
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error saat simpan ping {req.device}: {e}")
    finally:
        session.close()

    logger.info(f"[API] Ping {req.device} ({ip}) — {status.upper()} | {latency} ms")

    return {
        "status":     "ok",
        "device":     req.device,
        "ip_address": ip,
        "ping_result": status,
        "latency_ms":  latency,
        "checked_at":  datetime.now().isoformat(),
    }

@app.post("/reboot")
def reboot_device(req: RebootRequest):
    """
    Kirim command reboot ke device via SSH.
    Device akan disconnect setelah reboot — itu normal.
    """
    if req.device not in DEVICES:
        raise HTTPException(status_code=404, detail=f"Device '{req.device}' tidak ditemukan")

    cfg     = DEVICES[req.device]
    ip      = cfg['mgmt_ip']
    user    = cfg['ssh_user']
    passwd  = cfg['ssh_pass']
    cmd     = REBOOT_COMMANDS[cfg['type']]

    logger.info(f"[API] Reboot request: {req.device} ({ip})")

    result = ssh_execute(ip, user, passwd, cmd, timeout=10)

    # Reboot MikroTik akan disconnect SSH — itu expected, bukan error
    if not result['success']:
        # Kalau error-nya bukan karena koneksi terputus saat reboot
        if 'Connection reset' not in result['error'] and \
           'EOF' not in result['error'] and \
           'timed out' not in result['error'].lower():
            logger.error(f"Reboot gagal {req.device}: {result['error']}")
            raise HTTPException(
                status_code=500,
                detail=f"Reboot gagal: {result['error']}"
            )

    logger.info(f"[API] Reboot command terkirim ke {req.device}")

    return {
        "status":  "ok",
        "device":  req.device,
        "message": f"Reboot command berhasil dikirim ke {req.device}",
        "note":    "Device akan restart dalam beberapa detik",
        "sent_at": datetime.now().isoformat(),
    }