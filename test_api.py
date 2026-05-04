#!/usr/bin/env python3
"""
test_api.py — Test semua API endpoint secara interaktif via CLI
Jalankan: python3 test_api.py
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Konfigurasi ──────────────────────────────────────────────
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = os.getenv('API_PORT', '8000')

# Kalau API_HOST 0.0.0.0, gunakan localhost untuk request
HOST = 'localhost' if API_HOST == '0.0.0.0' else API_HOST
BASE_URL = f"http://{HOST}:{API_PORT}"


# ── Helper ───────────────────────────────────────────────────

def clear():
    os.system('clear')

def header(title: str):
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def pause():
    input("\nTekan Enter untuk lanjut...")

def ok(msg):
    print(f"  ✓ {msg}")

def err(msg):
    print(f"  ✗ {msg}")

def info(msg):
    print(f"  → {msg}")

def print_json(data: dict, indent: int = 4):
    print(json.dumps(data, indent=indent, ensure_ascii=False))

def request(method: str, path: str, body: dict = None) -> tuple[int, dict]:
    """HTTP request helper, return (status_code, response_dict)"""
    url  = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={'Content-Type': 'application/json'} if data else {}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"detail": str(e)}
    except urllib.error.URLError as e:
        return 0, {"detail": f"Tidak bisa connect ke {BASE_URL} — {e.reason}"}
    except Exception as e:
        return 0, {"detail": str(e)}


# ── Test Functions ───────────────────────────────────────────

def test_root():
    clear()
    header("TEST 1 — GET / (Health Check)")
    print(f"\n  URL: GET {BASE_URL}/\n")

    code, res = request('GET', '/')
    if code == 200:
        ok(f"Status: {code} OK")
        ok(f"Service: {res.get('service')}")
        ok(f"Version: {res.get('version', '-')}")
        ok(f"Time   : {res.get('time')}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_status_all():
    clear()
    header("TEST 2 — GET /status (Semua Device)")
    print(f"\n  URL: GET {BASE_URL}/status\n")

    code, res = request('GET', '/status')
    if code == 200 and res.get('status') == 'ok':
        ok(f"Status: {code} OK")
        ok(f"Total device: {len(res['data'])}")
        print()
        print(f"  {'Device':<16} {'IP':<16} {'Status':<8} {'Latency':<12} {'Checked At'}")
        print(f"  {'-'*16} {'-'*16} {'-'*8} {'-'*12} {'-'*22}")
        for d in res['data']:
            status  = '✓ UP' if d['status'] == 'up' else '✗ DOWN'
            latency = f"{d['latency_ms']} ms" if d['latency_ms'] else '-'
            print(f"  {d['device']:<16} {d['ip_address']:<16} {status:<8} {latency:<12} {d['checked_at'][:19]}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_status_one():
    clear()
    header("TEST 3 — GET /status/{device} (Satu Device)")

    # Ambil daftar device dulu
    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    devices = [d['name'] for d in res['data'] if d['is_active']]
    print(f"\n  Device aktif: {', '.join(devices)}")
    print()
    name = input("  Masukkan nama device: ").strip()

    print(f"\n  URL: GET {BASE_URL}/status/{name}\n")
    code, res = request('GET', f'/status/{name}')

    if code == 200:
        ok(f"Status    : {code} OK")
        ok(f"Device    : {res.get('device')}")
        ok(f"IP        : {res.get('ip_address')}")
        ok(f"Ping      : {res.get('ping_status', res.get('status'))}")
        ok(f"Latency   : {res.get('latency_ms')} ms")
        ok(f"Checked   : {res.get('checked_at', '')[:19]}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_ping():
    clear()
    header("TEST 4 — POST /ping (Ping Manual)")

    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    devices = [d['name'] for d in res['data'] if d['is_active']]
    print(f"\n  Device aktif: {', '.join(devices)}")
    print()
    name = input("  Masukkan nama device yang akan di-ping: ").strip()

    print(f"\n  URL: POST {BASE_URL}/ping")
    print(f"  Body: {{\"device\": \"{name}\"}}\n")

    code, res = request('POST', '/ping', {'device': name})

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status     : {code} OK")
        ok(f"Device     : {res.get('device')}")
        ok(f"IP         : {res.get('ip_address')}")
        ok(f"Ping result: {res.get('ping_result')}")
        ok(f"Latency    : {res.get('latency_ms')} ms")
        ok(f"Checked at : {res.get('checked_at', '')[:19]}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_reboot():
    clear()
    header("TEST 5 — POST /reboot (Reboot Device)")
    print()
    print("  PERINGATAN: Device akan benar-benar direboot!")
    print()

    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    devices = [d['name'] for d in res['data'] if d['is_active']]
    print(f"  Device aktif: {', '.join(devices)}")
    print()
    name = input("  Masukkan nama device yang akan direboot: ").strip()

    konfirmasi = input(f"\n  Yakin ingin reboot '{name}'? (ketik 'ya' untuk lanjut): ").strip()
    if konfirmasi.lower() != 'ya':
        print("\n  Dibatalkan.")
        pause()
        return

    print(f"\n  URL: POST {BASE_URL}/reboot")
    print(f"  Body: {{\"device\": \"{name}\"}}\n")

    code, res = request('POST', '/reboot', {'device': name})

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status : {code} OK")
        ok(f"Device : {res.get('device')}")
        ok(f"Message: {res.get('message')}")
        ok(f"Note   : {res.get('note')}")
        ok(f"Sent at: {res.get('sent_at', '')[:19]}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_list_devices():
    clear()
    header("TEST 6 — GET /api/devices (List Device)")
    print(f"\n  URL: GET {BASE_URL}/api/devices\n")

    code, res = request('GET', '/api/devices')

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status: {code} OK")
        ok(f"Total device: {len(res['data'])}")
        print()
        print(f"  {'ID':<4} {'Nama':<16} {'IP':<16} {'Tipe':<10} {'SNMP':<8} {'Status'}")
        print(f"  {'-'*4} {'-'*16} {'-'*16} {'-'*10} {'-'*8} {'-'*10}")
        for d in res['data']:
            status = 'AKTIF' if d['is_active'] else 'NONAKTIF'
            print(f"  {d['id']:<4} {d['name']:<16} {d['ip_address']:<16} {d['type']:<10} {d['snmp_community']:<8} {status}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_create_device():
    clear()
    header("TEST 7 — POST /api/devices (Tambah Device)")
    print()
    print("  Masukkan detail device baru:")
    print()
    name      = input("  Nama device                        : ").strip()
    ip        = input("  IP address                         : ").strip()
    dtype     = input("  Tipe [mikrotik/openwrt/linux]      : ").strip()
    ssh_user  = input("  SSH user        (default: admin)   : ").strip() or 'admin'
    ssh_pass  = input("  SSH password    (kosong = tidak ada): ").strip()
    community = input("  SNMP community  (default: public)  : ").strip() or 'public'
    desc      = input("  Deskripsi                          : ").strip()

    if not name or not ip or not dtype:
        err("Nama, IP, dan tipe wajib diisi!")
        pause()
        return

    body = {
        'name':           name,
        'ip_address':     ip,
        'type':           dtype,
        'ssh_user':       ssh_user,
        'ssh_pass':       ssh_pass,
        'snmp_community': community,
        'description':    desc,
    }

    print(f"\n  URL: POST {BASE_URL}/api/devices")
    print(f"  Body: {json.dumps(body)}\n")

    code, res = request('POST', '/api/devices', body)

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status : {code} OK")
        ok(f"Message: {res.get('message')}")
        ok(f"ID baru: {res.get('id')}")
        print()
        info("Device langsung aktif — akan dimonitor pada siklus berikutnya")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_update_device():
    clear()
    header("TEST 8 — PUT /api/devices/{id} (Update Device)")

    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    print()
    print(f"  {'ID':<4} {'Nama':<16} {'IP':<16} {'Tipe'}")
    print(f"  {'-'*4} {'-'*16} {'-'*16} {'-'*10}")
    for d in res['data']:
        print(f"  {d['id']:<4} {d['name']:<16} {d['ip_address']:<16} {d['type']}")
    print()

    try:
        device_id = int(input("  Masukkan ID device yang akan diupdate: ").strip())
    except ValueError:
        err("ID tidak valid")
        pause()
        return

    print()
    print("  Kosongkan field yang tidak ingin diubah:")
    print()
    ip        = input("  IP address baru        : ").strip()
    dtype     = input("  Tipe baru              : ").strip()
    ssh_user  = input("  SSH user baru          : ").strip()
    ssh_pass  = input("  SSH password baru      : ").strip()
    community = input("  SNMP community baru    : ").strip()
    desc      = input("  Deskripsi baru         : ").strip()

    body = {}
    if ip:        body['ip_address']     = ip
    if dtype:     body['type']           = dtype
    if ssh_user:  body['ssh_user']       = ssh_user
    if ssh_pass:  body['ssh_pass']       = ssh_pass
    if community: body['snmp_community'] = community
    if desc:      body['description']    = desc

    if not body:
        info("Tidak ada yang diubah.")
        pause()
        return

    print(f"\n  URL: PUT {BASE_URL}/api/devices/{device_id}")
    print(f"  Body: {json.dumps(body)}\n")

    code, res = request('PUT', f'/api/devices/{device_id}', body)

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status : {code} OK")
        ok(f"Message: {res.get('message')}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_toggle_device():
    clear()
    header("TEST 9 — PATCH /api/devices/{id}/toggle (Toggle Aktif)")

    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    print()
    print(f"  {'ID':<4} {'Nama':<16} {'IP':<16} {'Status'}")
    print(f"  {'-'*4} {'-'*16} {'-'*16} {'-'*10}")
    for d in res['data']:
        status = 'AKTIF' if d['is_active'] else 'NONAKTIF'
        print(f"  {d['id']:<4} {d['name']:<16} {d['ip_address']:<16} {status}")
    print()

    try:
        device_id = int(input("  Masukkan ID device yang akan di-toggle: ").strip())
    except ValueError:
        err("ID tidak valid")
        pause()
        return

    print(f"\n  URL: PATCH {BASE_URL}/api/devices/{device_id}/toggle\n")

    code, res = request('PATCH', f'/api/devices/{device_id}/toggle')

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status    : {code} OK")
        ok(f"Message   : {res.get('message')}")
        is_active = res.get('is_active')
        ok(f"Is active : {is_active} ({'AKTIF' if is_active else 'NONAKTIF'})")
        print()
        if is_active:
            info("Device akan mulai dimonitor pada siklus berikutnya")
        else:
            info("Device akan berhenti dimonitor pada siklus berikutnya")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_delete_device():
    clear()
    header("TEST 10 — DELETE /api/devices/{id} (Hapus Device)")
    print()
    print("  PERINGATAN: Device akan dihapus permanen dari monitoring!")
    print()

    code, res = request('GET', '/api/devices')
    if code != 200:
        err("Tidak bisa ambil daftar device")
        pause()
        return

    print(f"  {'ID':<4} {'Nama':<16} {'IP':<16} {'Status'}")
    print(f"  {'-'*4} {'-'*16} {'-'*16} {'-'*10}")
    for d in res['data']:
        status = 'AKTIF' if d['is_active'] else 'NONAKTIF'
        print(f"  {d['id']:<4} {d['name']:<16} {d['ip_address']:<16} {status}")
    print()

    try:
        device_id = int(input("  Masukkan ID device yang akan dihapus: ").strip())
    except ValueError:
        err("ID tidak valid")
        pause()
        return

    konfirmasi = input(f"\n  Yakin hapus device ID {device_id}? (ketik 'ya' untuk lanjut): ").strip()
    if konfirmasi.lower() != 'ya':
        print("\n  Dibatalkan.")
        pause()
        return

    print(f"\n  URL: DELETE {BASE_URL}/api/devices/{device_id}\n")

    code, res = request('DELETE', f'/api/devices/{device_id}')

    if code == 200 and res.get('status') == 'ok':
        ok(f"Status : {code} OK")
        ok(f"Message: {res.get('message')}")
    else:
        err(f"Status: {code}")
        print_json(res)
    pause()


def test_all_auto():
    """Jalankan semua test otomatis tanpa interaksi"""
    clear()
    header("TEST AUTO — SEMUA ENDPOINT")
    print(f"\n  Target: {BASE_URL}")
    print(f"  Waktu : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    results = []

    tests = [
        ('GET',   '/',              None,                          'Health check'),
        ('GET',   '/status',        None,                          'Status semua device'),
        ('GET',   '/api/devices',   None,                          'List devices'),
        ('POST',  '/api/devices',   {'name':'auto-test','ip_address':'192.168.99.99','type':'mikrotik'}, 'Tambah device test'),
        ('POST',  '/ping',          {'device': 'main-router'},     'Ping main-router'),
        ('GET',   '/status/main-router', None,                     'Status main-router'),
    ]

    created_id = None

    for method, path, body, label in tests:
        code, res = request(method, path, body)

        # Simpan ID device yang dibuat
        if path == '/api/devices' and method == 'POST' and code == 200:
            created_id = res.get('id')

        success = code == 200
        status  = '✓ PASS' if success else '✗ FAIL'
        results.append((status, method, path, code, label))
        print(f"  {status}  {method:<7} {path:<30} [{code}] {label}")

    # Toggle dan hapus device test
    if created_id:
        code, res = request('PATCH', f'/api/devices/{created_id}/toggle')
        success = code == 200
        status  = '✓ PASS' if success else '✗ FAIL'
        results.append((status, 'PATCH', f'/api/devices/{created_id}/toggle', code, 'Toggle device test'))
        print(f"  {status}  {'PATCH':<7} {f'/api/devices/{created_id}/toggle':<30} [{code}] Toggle device test")

        code, res = request('DELETE', f'/api/devices/{created_id}')
        success = code == 200
        status  = '✓ PASS' if success else '✗ FAIL'
        results.append((status, 'DELETE', f'/api/devices/{created_id}', code, 'Hapus device test'))
        print(f"  {status}  {'DELETE':<7} {f'/api/devices/{created_id}':<30} [{code}] Hapus device test")

    passed = sum(1 for r in results if '✓' in r[0])
    total  = len(results)
    print()
    print(f"  {'='*55}")
    print(f"  Hasil: {passed}/{total} test PASSED")
    if passed == total:
        print("  Status: SEMUA TEST BERHASIL ✓")
    else:
        print("  Status: ADA TEST YANG GAGAL ✗")
    print(f"  {'='*55}")
    pause()


# ── Main Menu ────────────────────────────────────────────────

def main():
    while True:
        clear()
        print("=" * 60)
        print("     API TEST CLI — NETWORK MONITORING")
        print("=" * 60)
        print(f"  Target : {BASE_URL}")
        print(f"  Waktu  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print()
        print("  ── Status & Ping ──────────────────────")
        print("  [1]  GET  /              (health check)")
        print("  [2]  GET  /status        (semua device)")
        print("  [3]  GET  /status/{name} (satu device)")
        print("  [4]  POST /ping          (ping manual)")
        print("  [5]  POST /reboot        (reboot device)")
        print()
        print("  ── Device Management ──────────────────")
        print("  [6]  GET    /api/devices      (list)")
        print("  [7]  POST   /api/devices      (tambah)")
        print("  [8]  PUT    /api/devices/{id} (update)")
        print("  [9]  PATCH  /api/devices/{id}/toggle")
        print("  [10] DELETE /api/devices/{id} (hapus)")
        print()
        print("  ── Auto Test ──────────────────────────")
        print("  [0]  Jalankan semua test otomatis")
        print("  [q]  Keluar")
        print()
        print("=" * 60)
        pilih = input("  Pilih: ").strip().lower()

        if   pilih == '1':  test_root()
        elif pilih == '2':  test_status_all()
        elif pilih == '3':  test_status_one()
        elif pilih == '4':  test_ping()
        elif pilih == '5':  test_reboot()
        elif pilih == '6':  test_list_devices()
        elif pilih == '7':  test_create_device()
        elif pilih == '8':  test_update_device()
        elif pilih == '9':  test_toggle_device()
        elif pilih == '10': test_delete_device()
        elif pilih == '0':  test_all_auto()
        elif pilih == 'q':
            print("\n  Keluar dari API Test CLI.\n")
            sys.exit(0)
        else:
            print("  Pilihan tidak valid.")
            import time; time.sleep(1)


if __name__ == '__main__':
    main()