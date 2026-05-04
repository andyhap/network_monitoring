"""
migrate.py — Jalankan sekali untuk setup/update schema database.
Aman dijalankan berulang kali (idempotent).
"""
from sqlalchemy import text
from models.database import engine, init_db, get_session, Device
from utils.logger import get_logger
import os
from dotenv import load_dotenv

load_dotenv()
logger = get_logger('migrate')


def migrate():
    print("=" * 50)
    print("  DATABASE MIGRATION")
    print("=" * 50)

    # Step 1 — Buat semua tabel yang belum ada
    print("\n[1/3] Membuat tabel baru jika belum ada...")
    init_db()

    # Step 2 — Verifikasi tabel devices ada
    print("[2/3] Verifikasi tabel devices...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'devices'
        """))
        count = result.scalar()
        if count:
            print("      Tabel 'devices' sudah ada.")
        else:
            print("      ERROR: Tabel 'devices' tidak ditemukan!")
            return

    # Step 3 — Seed device dari .env jika tabel masih kosong
    print("[3/3] Cek data device di database...")
    session = get_session()
    try:
        total = session.query(Device).count()
        if total > 0:
            print(f"      Sudah ada {total} device di database, skip seed.")
        else:
            print("      Tabel kosong, seed device dari .env...")
            devices = []

            main_ip = os.getenv('MAIN_ROUTER_IP')
            if main_ip:
                devices.append(Device(
                    name='main-router',
                    ip_address=main_ip,
                    type='mikrotik',
                    ssh_user=os.getenv('MAIN_ROUTER_SSH_USER', 'admin'),
                    ssh_pass=os.getenv('MAIN_ROUTER_SSH_PASS', ''),
                    snmp_community='public',
                    description='Main Router MikroTik CHR',
                    is_active=1
                ))

            kantor_ip = os.getenv('ROUTER_KANTOR_IP')
            if kantor_ip:
                devices.append(Device(
                    name='router-kantor',
                    ip_address=kantor_ip,
                    type='mikrotik',
                    ssh_user=os.getenv('ROUTER_KANTOR_SSH_USER', 'admin'),
                    ssh_pass=os.getenv('ROUTER_KANTOR_SSH_PASS', ''),
                    snmp_community='public',
                    description='Router Kantor MikroTik CHR',
                    is_active=1
                ))

            openwrt_ip = os.getenv('OPENWRT_IP')
            if openwrt_ip:
                devices.append(Device(
                    name='openwrt',
                    ip_address=openwrt_ip,
                    type='openwrt',
                    ssh_user=os.getenv('OPENWRT_SSH_USER', 'root'),
                    ssh_pass=os.getenv('OPENWRT_SSH_PASS', ''),
                    snmp_community='public',
                    description='Access Point OpenWRT 25.12',
                    is_active=1
                ))

            if devices:
                session.add_all(devices)
                session.commit()
                print(f"      {len(devices)} device berhasil di-seed:")
                for d in devices:
                    print(f"      - {d.name} ({d.ip_address}) [{d.type}]")
            else:
                print("      Tidak ada IP device di .env, skip seed.")
                print("      Tambahkan device via: python3 menu.py -> [7]")

    except Exception as e:
        session.rollback()
        print(f"      ERROR saat seed: {e}")
    finally:
        session.close()

    print()
    print("=" * 50)
    print("  MIGRASI SELESAI")
    print("=" * 50)
    print()

    # Tampilkan semua device
    session = get_session()
    try:
        devices = session.query(Device).all()
        if devices:
            print("  Device terdaftar:")
            for d in devices:
                status = "AKTIF" if d.is_active else "NONAKTIF"
                print(f"  [{d.id}] {d.name:<16} {d.ip_address:<16} {d.type:<10} {status}")
    finally:
        session.close()
    print()


if __name__ == '__main__':
    migrate()