import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from sqlalchemy import text
from models.database import get_session, DeviceStatus, SnmpMetric, InterfaceTraffic
from utils.logger import get_logger

load_dotenv()
logger = get_logger('supabase_backup')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Jumlah row terbaru yang dipertahankan di MariaDB lokal
# Cukup untuk 3 jam data tampil di frontend tanpa putus
RETAIN_ROWS = {
    'device_status':     1200,   # 3 device × 2/menit × 180 menit
    'snmp_metrics':      3500,   # 3 device × 6 OID × 1/menit × 180 menit
    'interface_traffic': 2500,   # 12 interface × 1/menit × 180 menit
}


def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL dan SUPABASE_KEY belum diisi di .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def backup_and_cleanup_table(
    client: Client,
    session,
    model,
    supabase_table: str,
    time_field: str,
    retain_rows: int,
    serialize_fn
) -> tuple[int, int]:
    """
    Backup row lama ke Supabase lalu hapus dari lokal.
    Yang dipertahankan: N row terbaru berdasarkan ID.
    Yang dibackup+hapus: semua row di luar N terbaru.

    Return: (jumlah_dibackup, jumlah_dihapus)
    """
    # Hitung total row
    total = session.query(model).count()

    if total <= retain_rows:
        logger.info(
            f"{model.__tablename__}: {total} row (retain={retain_rows}) "
            f"— tidak ada yang perlu dibackup"
        )
        return 0, 0

    # Cari ID batas — ambil ID ke-N dari belakang (terbaru)
    # Row dengan ID < cutoff_id → kandidat backup + hapus
    cutoff_row = (
        session.query(model.id)
        .order_by(model.id.desc())
        .offset(retain_rows - 1)
        .limit(1)
        .scalar()
    )

    if not cutoff_row:
        return 0, 0

    # Ambil semua row yang akan dibackup (id <= cutoff_id)
    old_records = session.query(model).filter(model.id <= cutoff_row).all()

    if not old_records:
        return 0, 0

    # Serialize ke list of dict
    data = [serialize_fn(r) for r in old_records]

    # Upload ke Supabase dalam batch 500 agar tidak timeout
    backed_up = 0
    batch_size = 500
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        try:
            client.table(supabase_table).insert(batch).execute()
            backed_up += len(batch)
        except Exception as e:
            logger.error(f"Gagal upload batch ke {supabase_table}: {e}")
            # data lokal tidak akan dihapus jika gagal
            session.rollback()
            return backed_up, 0

    # Hapus dari lokal hanya setelah semua berhasil diupload
    deleted = session.query(model).filter(model.id <= cutoff_row).delete()
    session.commit()

    logger.info(
        f"{model.__tablename__}: backup {backed_up} row → Supabase, "
        f"hapus {deleted} row dari lokal "
        f"(pertahankan {retain_rows} row terbaru)"
    )
    return backed_up, deleted


def run():
    """
    Jalankan backup + cleanup setiap 60 menit:
    - Backup row lama (di luar N terbaru) ke Supabase
    - Hapus row yang sudah dibackup dari MariaDB lokal
    - Data terbaru tetap aman di lokal untuk frontend
    """
    logger.info("=== Backup & Cleanup mulai ===")

    try:
        client  = get_supabase_client()
        session = get_session()

        total_backed  = 0
        total_deleted = 0

        # device_status
        b, d = backup_and_cleanup_table(
            client, session,
            model=DeviceStatus,
            supabase_table='device_status_backup',
            time_field='checked_at',
            retain_rows=RETAIN_ROWS['device_status'],
            serialize_fn=lambda r: {
                'device':     r.device,
                'ip_address': r.ip_address,
                'status':     r.status,
                'latency_ms': r.latency_ms,
                'checked_at': r.checked_at.isoformat(),
            }
        )
        total_backed += b
        total_deleted += d

        # snmp_metrics
        b, d = backup_and_cleanup_table(
            client, session,
            model=SnmpMetric,
            supabase_table='snmp_metrics_backup',
            time_field='collected_at',
            retain_rows=RETAIN_ROWS['snmp_metrics'],
            serialize_fn=lambda r: {
                'device':       r.device,
                'ip_address':   r.ip_address,
                'metric_name':  r.metric_name,
                'metric_value': r.metric_value,
                'collected_at': r.collected_at.isoformat(),
            }
        )
        total_backed += b
        total_deleted += d

        # interface_traffic
        b, d = backup_and_cleanup_table(
            client, session,
            model=InterfaceTraffic,
            supabase_table='interface_traffic_backup',
            time_field='collected_at',
            retain_rows=RETAIN_ROWS['interface_traffic'],
            serialize_fn=lambda r: {
                'device':         r.device,
                'ip_address':     r.ip_address,
                'interface_name': r.interface_name,
                'bytes_in':       r.bytes_in,
                'bytes_out':      r.bytes_out,
                'packets_in':     r.packets_in,
                'packets_out':    r.packets_out,
                'collected_at':   r.collected_at.isoformat(),
            }
        )
        total_backed += b
        total_deleted += d

        session.close()
        logger.info(
            f"=== Selesai: {total_backed} records di-backup, "
            f"{total_deleted} records dihapus dari lokal ==="
        )

    except ValueError as e:
        logger.error(f"Konfigurasi Supabase belum lengkap: {e}")
    except Exception as e:
        logger.error(f"Backup error: {e}")