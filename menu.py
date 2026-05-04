import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from models.database import get_session, DeviceStatus, SnmpMetric, InterfaceTraffic
from backup.supabase_backup import run as backup_run, get_supabase_client, RETAIN_ROWS
from utils.logger import get_logger

load_dotenv()
logger = get_logger('menu')

# ── Helper tampilan ──────────────────────────────────────────

def clear():
    os.system('clear')

def header(title: str):
    print("=" * 52)
    print(f"  {title}")
    print("=" * 52)

def pause():
    input("\nTekan Enter untuk kembali ke menu...")

def fmt_bytes(b: int) -> str:
    if b >= 1_000_000_000:
        return f"{b/1_000_000_000:.2f} GB"
    elif b >= 1_000_000:
        return f"{b/1_000_000:.2f} MB"
    elif b >= 1_000:
        return f"{b/1_000:.2f} KB"
    return f"{b} B"

def print_table(headers: list, rows: list, col_widths: list):
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*[str(v) for v in row]))

# ── Menu 1 — Status Perangkat Realtime ──────────────────────

def menu_status():
    clear()
    header("STATUS PERANGKAT — REALTIME")
    session = get_session()
    try:
        # Ambil data terbaru per device
        from sqlalchemy import func
        subq = (
            session.query(
                DeviceStatus.device,
                func.max(DeviceStatus.id).label('max_id')
            ).group_by(DeviceStatus.device).subquery()
        )
        records = (
            session.query(DeviceStatus)
            .join(subq, DeviceStatus.id == subq.c.max_id)
            .order_by(DeviceStatus.device)
            .all()
        )

        if not records:
            print("\n  Belum ada data. Jalankan main.py terlebih dahulu.")
        else:
            print()
            print_table(
                ['Perangkat', 'IP', 'Status', 'Latency', 'Terakhir Dicek'],
                [
                    [
                        r.device,
                        r.ip_address,
                        '✓ UP' if r.status == 'up' else '✗ DOWN',
                        f"{r.latency_ms} ms" if r.latency_ms else '-',
                        r.checked_at.strftime('%Y-%m-%d %H:%M:%S')
                    ]
                    for r in records
                ],
                [16, 16, 8, 12, 22]
            )
    finally:
        session.close()
    pause()

# ── Menu 2 — Log Lokal ──────────────────────────────────────

def menu_log_lokal():
    clear()
    header("LOG LOKAL — 20 DATA TERBARU")
    print("\n  [1] Ping / Device Status")
    print("  [2] SNMP Metrics")
    print("  [3] Interface Traffic")
    print("  [0] Kembali")
    print()
    pilih = input("Pilih: ").strip()

    session = get_session()
    try:
        if pilih == '1':
            clear()
            header("LOG — DEVICE STATUS (20 terbaru)")
            records = session.query(DeviceStatus).order_by(
                DeviceStatus.id.desc()).limit(20).all()
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Status', 'Latency (ms)'],
                [[r.checked_at.strftime('%Y-%m-%d %H:%M:%S'),
                  r.device, r.status,
                  r.latency_ms if r.latency_ms else '-']
                 for r in records],
                [22, 16, 8, 12]
            )

        elif pilih == '2':
            clear()
            header("LOG — SNMP METRICS (20 terbaru)")
            records = session.query(SnmpMetric).order_by(
                SnmpMetric.id.desc()).limit(20).all()
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Metric', 'Value'],
                [[r.collected_at.strftime('%Y-%m-%d %H:%M:%S'),
                  r.device, r.metric_name,
                  str(r.metric_value)[:30]]
                 for r in records],
                [22, 16, 18, 32]
            )

        elif pilih == '3':
            clear()
            header("LOG — INTERFACE TRAFFIC (20 terbaru)")
            records = session.query(InterfaceTraffic).order_by(
                InterfaceTraffic.id.desc()).limit(20).all()
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Interface', 'In', 'Out'],
                [[r.collected_at.strftime('%Y-%m-%d %H:%M:%S'),
                  r.device, r.interface_name,
                  fmt_bytes(r.bytes_in), fmt_bytes(r.bytes_out)]
                 for r in records],
                [22, 16, 12, 12, 12]
            )

        elif pilih == '0':
            return
        else:
            print("  Pilihan tidak valid.")

    finally:
        session.close()
    pause()

# ── Menu 3 — Lihat Backup Supabase ──────────────────────────

def menu_log_supabase():
    clear()
    header("LOG BACKUP — SUPABASE (20 terbaru)")
    print("\n  [1] Device Status")
    print("  [2] SNMP Metrics")
    print("  [3] Interface Traffic")
    print("  [0] Kembali")
    print()
    pilih = input("Pilih: ").strip()

    if pilih == '0':
        return

    try:
        client = get_supabase_client()

        if pilih == '1':
            clear()
            header("BACKUP SUPABASE — DEVICE STATUS")
            res = (client.table('device_status_backup')
                   .select('checked_at,device,status,latency_ms')
                   .order('checked_at', desc=True).limit(20).execute())
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Status', 'Latency (ms)'],
                [[r['checked_at'][:19], r['device'],
                  r['status'], r['latency_ms'] or '-']
                 for r in res.data],
                [22, 16, 8, 12]
            )

        elif pilih == '2':
            clear()
            header("BACKUP SUPABASE — SNMP METRICS")
            res = (client.table('snmp_metrics_backup')
                   .select('collected_at,device,metric_name,metric_value')
                   .order('collected_at', desc=True).limit(20).execute())
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Metric', 'Value'],
                [[r['collected_at'][:19], r['device'],
                  r['metric_name'], str(r['metric_value'])[:30]]
                 for r in res.data],
                [22, 16, 18, 32]
            )

        elif pilih == '3':
            clear()
            header("BACKUP SUPABASE — INTERFACE TRAFFIC")
            res = (client.table('interface_traffic_backup')
                   .select('collected_at,device,interface_name,bytes_in,bytes_out')
                   .order('collected_at', desc=True).limit(20).execute())
            print()
            print_table(
                ['Waktu', 'Perangkat', 'Interface', 'In', 'Out'],
                [[r['collected_at'][:19], r['device'],
                  r['interface_name'],
                  fmt_bytes(r['bytes_in']), fmt_bytes(r['bytes_out'])]
                 for r in res.data],
                [22, 16, 12, 12, 12]
            )

        else:
            print("  Pilihan tidak valid.")

    except Exception as e:
        print(f"\n  Error koneksi Supabase: {e}")

    pause()

# ── Menu 4 — Backup Manual ──────────────────────────────────

def menu_backup_manual():
    clear()
    header("BACKUP MANUAL KE SUPABASE")
    print("\n  Menjalankan backup sekarang...")
    print()
    backup_run()
    pause()

# ── Menu 5 — Statistik Database ─────────────────────────────

def menu_statistik():
    clear()
    header("STATISTIK DATABASE")
    session = get_session()
    try:
        ds_total  = session.query(DeviceStatus).count()
        sm_total  = session.query(SnmpMetric).count()
        it_total  = session.query(InterfaceTraffic).count()

        ds_oldest = session.query(DeviceStatus).order_by(DeviceStatus.id.asc()).first()
        ds_newest = session.query(DeviceStatus).order_by(DeviceStatus.id.desc()).first()

        print()
        print("  DATABASE LOKAL (MariaDB)")
        print_table(
            ['Tabel', 'Total Row', 'Retain Max', 'Penuh (%)'],
            [
                ['device_status',     ds_total,
                 RETAIN_ROWS['device_status'],
                 f"{ds_total/RETAIN_ROWS['device_status']*100:.1f}%"],
                ['snmp_metrics',      sm_total,
                 RETAIN_ROWS['snmp_metrics'],
                 f"{sm_total/RETAIN_ROWS['snmp_metrics']*100:.1f}%"],
                ['interface_traffic', it_total,
                 RETAIN_ROWS['interface_traffic'],
                 f"{it_total/RETAIN_ROWS['interface_traffic']*100:.1f}%"],
            ],
            [20, 10, 12, 10]
        )

        if ds_oldest and ds_newest:
            print()
            print(f"  Data terlama : {ds_oldest.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Data terbaru : {ds_newest.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")

        # Statistik Supabase
        print()
        print("  DATABASE BACKUP (Supabase)")
        try:
            client = get_supabase_client()
            for tbl in ['device_status_backup', 'snmp_metrics_backup', 'interface_traffic_backup']:
                res = client.table(tbl).select('id', count='exact').execute()
                print(f"  {tbl:<35} {res.count} records")
        except Exception as e:
            print(f"  Gagal koneksi Supabase: {e}")

    finally:
        session.close()
    pause()

# ── Menu 6 — Export CSV ─────────────────────────────────────

import csv

def menu_export_csv():
    clear()
    header("EXPORT DATA KE CSV")
    print()
    print("  Sumber data:")
    print("  [1] Dari MariaDB lokal")
    print("  [2] Dari Supabase backup")
    print("  [0] Kembali")
    print()
    sumber = input("Pilih sumber: ").strip()

    if sumber == '0':
        return

    print()
    print("  Data yang diekspor:")
    print("  [1] Device Status")
    print("  [2] SNMP Metrics")
    print("  [3] Interface Traffic")
    print("  [4] Semua (3 file sekaligus)")
    print("  [0] Kembali")
    print()
    pilih = input("Pilih data: ").strip()

    if pilih == '0':
        return

    # Tentukan folder output
    export_dir = os.path.join(os.path.dirname(__file__), 'exports')
    os.makedirs(export_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if sumber == '1':
        _export_csv_lokal(pilih, export_dir, timestamp)
    elif sumber == '2':
        _export_csv_supabase(pilih, export_dir, timestamp)
    else:
        print("  Pilihan tidak valid.")
        pause()


def _export_csv_lokal(pilih: str, export_dir: str, timestamp: str):
    session = get_session()
    try:
        if pilih in ('1', '4'):
            records = session.query(DeviceStatus).order_by(DeviceStatus.id.desc()).all()
            fname = os.path.join(export_dir, f'device_status_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['id', 'device', 'ip_address', 'status', 'latency_ms', 'checked_at'])
                for r in records:
                    w.writerow([r.id, r.device, r.ip_address, r.status,
                                r.latency_ms, r.checked_at])
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(records)} records diekspor")

        if pilih in ('2', '4'):
            records = session.query(SnmpMetric).order_by(SnmpMetric.id.desc()).all()
            fname = os.path.join(export_dir, f'snmp_metrics_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['id', 'device', 'ip_address', 'metric_name',
                            'metric_value', 'collected_at'])
                for r in records:
                    w.writerow([r.id, r.device, r.ip_address,
                                r.metric_name, r.metric_value, r.collected_at])
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(records)} records diekspor")

        if pilih in ('3', '4'):
            records = session.query(InterfaceTraffic).order_by(
                InterfaceTraffic.id.desc()).all()
            fname = os.path.join(export_dir, f'interface_traffic_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['id', 'device', 'ip_address', 'interface_name',
                            'bytes_in', 'bytes_out', 'packets_in',
                            'packets_out', 'collected_at'])
                for r in records:
                    w.writerow([r.id, r.device, r.ip_address,
                                r.interface_name, r.bytes_in, r.bytes_out,
                                r.packets_in, r.packets_out, r.collected_at])
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(records)} records diekspor")

        if pilih not in ('1', '2', '3', '4'):
            print("  Pilihan tidak valid.")

    finally:
        session.close()
    pause()


def _export_csv_supabase(pilih: str, export_dir: str, timestamp: str):
    try:
        client = get_supabase_client()

        if pilih in ('1', '4'):
            res = (client.table('device_status_backup')
                   .select('*').order('checked_at', desc=True).execute())
            fname = os.path.join(export_dir, f'device_status_backup_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                if res.data:
                    w = csv.DictWriter(f, fieldnames=res.data[0].keys())
                    w.writeheader()
                    w.writerows(res.data)
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(res.data)} records diekspor")

        if pilih in ('2', '4'):
            res = (client.table('snmp_metrics_backup')
                   .select('*').order('collected_at', desc=True).execute())
            fname = os.path.join(export_dir, f'snmp_metrics_backup_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                if res.data:
                    w = csv.DictWriter(f, fieldnames=res.data[0].keys())
                    w.writeheader()
                    w.writerows(res.data)
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(res.data)} records diekspor")

        if pilih in ('3', '4'):
            res = (client.table('interface_traffic_backup')
                   .select('*').order('collected_at', desc=True).execute())
            fname = os.path.join(export_dir, f'interface_traffic_backup_{timestamp}.csv')
            with open(fname, 'w', newline='') as f:
                if res.data:
                    w = csv.DictWriter(f, fieldnames=res.data[0].keys())
                    w.writeheader()
                    w.writerows(res.data)
            print(f"\n  ✓ Disimpan: {fname}")
            print(f"    {len(res.data)} records diekspor")

        if pilih not in ('1', '2', '3', '4'):
            print("  Pilihan tidak valid.")

    except Exception as e:
        print(f"\n  Error koneksi Supabase: {e}")
    pause()

# ── Menu 7 — Manajemen Device ────────────────────────────────

def menu_device():
    while True:
        clear()
        header("MANAJEMEN DEVICE")
        print()
        print("  [1] Lihat semua device")
        print("  [2] Tambah device baru")
        print("  [3] Toggle aktif / nonaktif")
        print("  [4] Hapus device permanen")
        print("  [0] Kembali")
        print()
        pilih = input("Pilih: ").strip()

        if   pilih == '0': break
        elif pilih == '1': _device_list()
        elif pilih == '2': _device_add()
        elif pilih == '3': _device_toggle()
        elif pilih == '4': _device_delete()
        else:
            print("  Pilihan tidak valid.")
            pause()


def _device_list():
    clear()
    header("DAFTAR SEMUA DEVICE")
    from models.database import Device
    session = get_session()
    try:
        devices = session.query(Device).order_by(Device.id).all()
        if not devices:
            print("\n  Belum ada device terdaftar.")
        else:
            print()
            print_table(
                ['ID', 'Nama', 'IP', 'Tipe', 'SNMP', 'Status', 'Keterangan'],
                [[d.id, d.name, d.ip_address, d.type,
                  d.snmp_community,
                  'AKTIF' if d.is_active else 'NONAKTIF',
                  d.description or '-']
                 for d in devices],
                [4, 16, 16, 10, 8, 10, 20]
            )
    finally:
        session.close()
    pause()


def _device_list_simple():
    from models.database import Device
    session = get_session()
    try:
        devices = session.query(Device).order_by(Device.id).all()
        print_table(
            ['ID', 'Nama', 'IP', 'Status'],
            [[d.id, d.name, d.ip_address,
              'AKTIF' if d.is_active else 'NONAKTIF']
             for d in devices],
            [4, 18, 18, 10]
        )
    finally:
        session.close()


def _device_add():
    clear()
    header("TAMBAH DEVICE BARU")
    print()
    name      = input("  Nama device (contoh: router-baru)  : ").strip()
    ip        = input("  IP address                         : ").strip()
    dtype     = input("  Tipe [mikrotik/openwrt/linux]      : ").strip()
    ssh_user  = input("  SSH user        (default: admin)   : ").strip() or 'admin'
    ssh_pass  = input("  SSH password    (kosong = tidak ada): ").strip()
    community = input("  SNMP community  (default: public)  : ").strip() or 'public'
    desc      = input("  Deskripsi                          : ").strip()

    if not name or not ip or not dtype:
        print("\n  Error: nama, IP, dan tipe wajib diisi!")
        pause()
        return

    if dtype not in ('mikrotik', 'openwrt', 'linux'):
        print("\n  Error: tipe harus mikrotik, openwrt, atau linux!")
        pause()
        return

    from models.database import Device
    session = get_session()
    try:
        existing = session.query(Device).filter(Device.name == name).first()
        if existing:
            print(f"\n  Error: device '{name}' sudah ada!")
            pause()
            return

        device = Device(
            name=name, ip_address=ip, type=dtype,
            ssh_user=ssh_user, ssh_pass=ssh_pass,
            snmp_community=community, description=desc,
            is_active=1
        )
        session.add(device)
        session.commit()
        print(f"\n  ✓ Device '{name}' ({ip}) berhasil ditambahkan!")
        print("    Monitoring akan mulai pada siklus berikutnya.")
    except Exception as e:
        session.rollback()
        print(f"\n  Error: {e}")
    finally:
        session.close()
    pause()


def _device_toggle():
    clear()
    header("TOGGLE AKTIF / NONAKTIF DEVICE")
    print()
    _device_list_simple()
    print()
    try:
        device_id = int(input("  Masukkan ID device: ").strip())
    except ValueError:
        print("  ID tidak valid.")
        pause()
        return

    from models.database import Device
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            print(f"\n  Device ID {device_id} tidak ditemukan!")
            pause()
            return

        device.is_active = 0 if device.is_active == 1 else 1
        session.commit()
        status = "DIAKTIFKAN" if device.is_active == 1 else "DINONAKTIFKAN"
        print(f"\n  ✓ Device '{device.name}' berhasil {status}!")
        if device.is_active == 0:
            print("    Monitoring akan berhenti pada siklus berikutnya.")
        else:
            print("    Monitoring akan mulai pada siklus berikutnya.")
    except Exception as e:
        session.rollback()
        print(f"\n  Error: {e}")
    finally:
        session.close()
    pause()


def _device_delete():
    clear()
    header("HAPUS DEVICE PERMANEN")
    print()
    print("  PERINGATAN: Semua data monitoring device akan:")
    print("  1. Di-archive ke Supabase (deleted_* tables)")
    print("  2. Dihapus dari database lokal")
    print("  3. Device dihapus dari daftar monitoring")
    print()
    _device_list_simple()
    print()
    try:
        device_id = int(input("  Masukkan ID device yang akan dihapus: ").strip())
    except ValueError:
        print("  ID tidak valid.")
        pause()
        return

    from models.database import Device, DeviceStatus, SnmpMetric, InterfaceTraffic
    from backup.supabase_backup import get_supabase_client
    session = get_session()
    try:
        device = session.query(Device).filter(Device.id == device_id).first()
        if not device:
            print(f"\n  Device ID {device_id} tidak ditemukan!")
            pause()
            return

        # Hitung jumlah data
        ds_count = session.query(DeviceStatus).filter(DeviceStatus.device == device.name).count()
        sm_count = session.query(SnmpMetric).filter(SnmpMetric.device == device.name).count()
        it_count = session.query(InterfaceTraffic).filter(InterfaceTraffic.device == device.name).count()

        print(f"\n  Device  : {device.name} ({device.ip_address})")
        print(f"  Data yang akan di-archive & dihapus:")
        print(f"    device_status     : {ds_count} records")
        print(f"    snmp_metrics      : {sm_count} records")
        print(f"    interface_traffic : {it_count} records")
        print()

        konfirmasi = input("  Ketik 'ya' untuk konfirmasi: ").strip()
        if konfirmasi.lower() != 'ya':
            print("  Dibatalkan.")
            pause()
            return

        name = device.name
        now  = datetime.now().isoformat()
        device_info = {
            'id': device.id, 'name': device.name,
            'ip_address': device.ip_address, 'type': device.type,
        }

        print(f"\n  Mengarchive data ke Supabase...")
        client = get_supabase_client()

        # Archive device_status
        ds_records = session.query(DeviceStatus).filter(DeviceStatus.device == name).all()
        if ds_records:
            client.table('deleted_device_status').insert([{
                'device': r.device, 'ip_address': r.ip_address,
                'status': r.status, 'latency_ms': r.latency_ms,
                'checked_at': r.checked_at.isoformat(),
                'deleted_at': now, 'device_info': device_info,
            } for r in ds_records]).execute()
            print(f"  ✓ Archive {len(ds_records)} device_status records")

        # Archive snmp_metrics
        sm_records = session.query(SnmpMetric).filter(SnmpMetric.device == name).all()
        if sm_records:
            for i in range(0, len(sm_records), 500):
                batch = sm_records[i:i+500]
                client.table('deleted_snmp_metrics').insert([{
                    'device': r.device, 'ip_address': r.ip_address,
                    'metric_name': r.metric_name, 'metric_value': r.metric_value,
                    'collected_at': r.collected_at.isoformat(),
                    'deleted_at': now, 'device_info': device_info,
                } for r in batch]).execute()
            print(f"  ✓ Archive {len(sm_records)} snmp_metrics records")

        # Archive interface_traffic
        it_records = session.query(InterfaceTraffic).filter(InterfaceTraffic.device == name).all()
        if it_records:
            for i in range(0, len(it_records), 500):
                batch = it_records[i:i+500]
                client.table('deleted_interface_traffic').insert([{
                    'device': r.device, 'ip_address': r.ip_address,
                    'interface_name': r.interface_name,
                    'bytes_in': r.bytes_in, 'bytes_out': r.bytes_out,
                    'packets_in': r.packets_in, 'packets_out': r.packets_out,
                    'collected_at': r.collected_at.isoformat(),
                    'deleted_at': now, 'device_info': device_info,
                } for r in batch]).execute()
            print(f"  ✓ Archive {len(it_records)} interface_traffic records")

        # Hapus dari lokal
        print(f"\n  Menghapus data dari database lokal...")
        session.query(DeviceStatus).filter(DeviceStatus.device == name).delete()
        session.query(SnmpMetric).filter(SnmpMetric.device == name).delete()
        session.query(InterfaceTraffic).filter(InterfaceTraffic.device == name).delete()
        session.delete(device)
        session.commit()

        print(f"  ✓ Device '{name}' dan semua datanya berhasil dihapus!")
        print(f"  ✓ Data tersimpan di Supabase (deleted_* tables)")

    except Exception as e:
        session.rollback()
        print(f"\n  Error: {e}")
    finally:
        session.close()
    pause()

# ── Main Menu ────────────────────────────────────────────────

def main():
    while True:
        clear()
        print("=" * 52)
        print("     NETWORK MONITORING — MENU UTAMA")
        print("=" * 52)
        print(f"  Waktu : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 52)
        print("  [1] Status perangkat (realtime)")
        print("  [2] Lihat log lokal")
        print("  [3] Lihat backup Supabase")
        print("  [4] Backup manual ke Supabase")
        print("  [5] Statistik database")
        print("  [6] Export data ke CSV")
        print("  [7] Manajemen device")
        print("  [0] Keluar")
        print("=" * 52)
        pilih = input("Pilih menu: ").strip()

        if   pilih == '1': menu_status()
        elif pilih == '2': menu_log_lokal()
        elif pilih == '3': menu_log_supabase()
        elif pilih == '4': menu_backup_manual()
        elif pilih == '5': menu_statistik()
        elif pilih == '6': menu_export_csv()
        elif pilih == '7': menu_device()
        elif pilih == '0':
            print("\n  Keluar dari menu. Monitoring tetap berjalan.\n")
            sys.exit(0)
        else:
            print("  Pilihan tidak valid.")
            pause()

if __name__ == '__main__':
    main()