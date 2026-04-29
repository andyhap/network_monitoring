# 🖥️ Network Monitoring — Python

Sistem monitoring jaringan berbasis Python untuk simulasi jaringan menggunakan GNS3 + VirtualBox. Memonitor status perangkat, traffic bandwidth, dan metrics SNMP secara realtime dengan backup otomatis ke Supabase.

---

## 📋 Daftar Isi

- [Arsitektur](#arsitektur)
- [Stack & Library](#stack--library)
- [Persyaratan Sistem](#persyaratan-sistem)
- [Struktur Project](#struktur-project)
- [Instalasi](#instalasi)
- [Konfigurasi](#konfigurasi)
- [Menjalankan Program](#menjalankan-program)
- [API Endpoints](#api-endpoints)
- [Menu CLI](#menu-cli)
- [Backup Supabase](#backup-supabase)
- [Troubleshooting](#troubleshooting)

---

## Arsitektur

```
Internet
    │
Cloudflare Zero Trust Tunnel
    │
    └── monitoring.domain.com → FastAPI (port 8000)
                                 di server Debian

Laravel (hosting terpisah)
    └── hit API via HTTPS → monitoring.domain.com
    └── baca histori      → Supabase

Server Debian (GNS3)
    ├── main.py       → polling SNMP, ping, bandwidth (scheduler)
    ├── menu.py       → CLI menu monitoring
    ├── api/          → FastAPI (reboot, ping now, status)
    └── backup/       → backup otomatis ke Supabase tiap 60 menit

Topologi Jaringan:
    NAT/Internet
         │
    [main-router] MikroTik CHR — ether3=192.168.99.1 (management)
         │
    [router-kantor] MikroTik CHR — ether4=192.168.99.3 (management)
         │              │
    [Switch-1]     [openWRT] — eth2=192.168.99.4 (management)
    PC Kantor x3        │
                   [Switch-3]
                   PC Tamu x3

    [Switch-2] — Management Network (192.168.99.0/24)
         │
    [monitoring-server] Debian — enp0s3=192.168.99.2
```

---

## Stack & Library

| Library | Versi | Fungsi |
|---------|-------|--------|
| Python | 3.11+ | Runtime |
| FastAPI | latest | REST API server |
| uvicorn | latest | ASGI server untuk FastAPI |
| SQLAlchemy | 2.x | ORM database |
| PyMySQL | latest | MySQL/MariaDB connector |
| easysnmp | latest | SNMP polling |
| icmplib | latest | Ping/ICMP monitoring |
| paramiko | latest | SSH untuk reboot device |
| schedule | latest | Job scheduler |
| supabase | latest | Backup ke Supabase |
| python-dotenv | latest | Manajemen environment variables |

---

## Persyaratan Sistem

- **OS:** Debian/Ubuntu Linux
- **Python:** 3.11 ke atas
- **Database:** MariaDB atau MySQL
- **Akun:** Supabase (untuk backup)
- **Network:** Akses ke management network perangkat (192.168.99.0/24)

---

## Struktur Project

```
monitoring/
├── .env                      # konfigurasi (tidak di-commit)
├── .env.example              # template environment variables
├── .gitignore
├── main.py                   # entry point scheduler utama
├── menu.py                   # CLI menu interaktif
├── requirements.txt
├── api/
│   ├── __init__.py
│   ├── main_api.py           # FastAPI endpoints
│   └── run_api.py            # entry point API server
├── backup/
│   ├── __init__.py
│   └── supabase_backup.py    # backup & cleanup ke Supabase
├── collectors/
│   ├── __init__.py
│   ├── bandwidth.py          # traffic per interface via SNMP
│   ├── ping_monitor.py       # status up/down & latency
│   └── snmp_collector.py     # metrics SNMP (sysName, uptime, dll)
├── models/
│   ├── __init__.py
│   └── database.py           # schema tabel & koneksi DB
├── utils/
│   ├── __init__.py
│   └── logger.py             # logging ke file & terminal
├── logs/                     # file log (tidak di-commit)
│   ├── monitor.log
│   └── api.log
└── exports/                  # hasil export CSV (tidak di-commit)
```

---

## Instalasi

### 1. Clone Repository

```bash
git clone https://github.com/username/monitoring.git
cd monitoring
```

### 2. Install Dependency Sistem

```bash
sudo apt update && sudo apt upgrade -y

# Python tools
sudo apt install -y python3-pip python3-venv python3-dev

# MariaDB
sudo apt install -y mariadb-server mariadb-client

# Library SNMP sistem
sudo apt install -y libsnmp-dev snmp snmp-mibs-downloader

# Build tools
sudo apt install -y gcc build-essential
```

### 3. Nonaktifkan APIPA (Khusus VirtualBox)

> Jika server berjalan di VirtualBox, jalankan langkah ini agar interface
> tidak mendapat IP 169.254.x.x yang menyebabkan konflik routing.

```bash
sudo nano /etc/sysctl.d/no-apipa.conf
```

Isi dengan:

```
net.ipv4.conf.all.autoconf = 0
net.ipv4.conf.default.autoconf = 0
```

Terapkan:

```bash
sudo sysctl --system
```

### 4. Setup MariaDB

```bash
# Jalankan setup awal
sudo mysql_secure_installation
# Jawab Y untuk semua, set root password

# Masuk ke MariaDB
sudo mysql -u root -p
```

Jalankan SQL berikut:

```sql
CREATE DATABASE monitoring_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'monitor_user'@'localhost' IDENTIFIED BY 'ganti_password_ini';
GRANT ALL PRIVILEGES ON monitoring_db.* TO 'monitor_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 5. Buat Virtual Environment

```bash
cd ~/monitoring
python3 -m venv venv
source venv/bin/activate
```

### 6. Install Library Python

```bash
pip install -r requirements.txt
```

Atau install manual:

```bash
pip install easysnmp pymysql sqlalchemy icmplib schedule python-dotenv
pip install fastapi uvicorn paramiko supabase
```

### 7. Setup Capability untuk icmplib

> icmplib membutuhkan raw socket untuk mengirim ICMP packet.
> Gunakan `setcap` agar tidak perlu `sudo` setiap kali menjalankan program.

```bash
sudo setcap cap_net_raw+ep ~/monitoring/venv/bin/python3

# Verifikasi
getcap ~/monitoring/venv/bin/python3
# Output: /home/user/monitoring/venv/bin/python3 cap_net_raw+ep
```

> **Catatan:** Jika Python di-upgrade atau venv di-recreate,
> jalankan `setcap` ini lagi.

### 8. Setup Tabel Supabase

Masuk ke **Supabase Dashboard → SQL Editor**, jalankan:

```sql
-- Tabel backup device status
CREATE TABLE device_status_backup (
    id          BIGSERIAL PRIMARY KEY,
    device      VARCHAR(50)  NOT NULL,
    ip_address  VARCHAR(20)  NOT NULL,
    status      VARCHAR(10)  NOT NULL,
    latency_ms  FLOAT,
    checked_at  TIMESTAMPTZ  NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Tabel backup SNMP metrics
CREATE TABLE snmp_metrics_backup (
    id            BIGSERIAL PRIMARY KEY,
    device        VARCHAR(50)  NOT NULL,
    ip_address    VARCHAR(20)  NOT NULL,
    metric_name   VARCHAR(100) NOT NULL,
    metric_value  TEXT,
    collected_at  TIMESTAMPTZ  NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

-- Tabel backup interface traffic
CREATE TABLE interface_traffic_backup (
    id              BIGSERIAL PRIMARY KEY,
    device          VARCHAR(50) NOT NULL,
    ip_address      VARCHAR(20) NOT NULL,
    interface_name  VARCHAR(50) NOT NULL,
    bytes_in        BIGINT      DEFAULT 0,
    bytes_out       BIGINT      DEFAULT 0,
    packets_in      BIGINT      DEFAULT 0,
    packets_out     BIGINT      DEFAULT 0,
    collected_at    TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index untuk query cepat
CREATE INDEX idx_ds ON device_status_backup  (device, checked_at DESC);
CREATE INDEX idx_sm ON snmp_metrics_backup   (device, collected_at DESC);
CREATE INDEX idx_it ON interface_traffic_backup (device, collected_at DESC);
```

---

## Konfigurasi

### 1. Buat File .env

```bash
cp .env.example .env
nano .env
```

Isi semua variabel:

```env
# ── Database MariaDB ──────────────────────────────
DB_HOST=localhost
DB_PORT=3306
DB_NAME=monitoring_db
DB_USER=monitor_user
DB_PASS=ganti_password_ini

# ── SNMP ─────────────────────────────────────────
SNMP_COMMUNITY=public
SNMP_PORT=161

# ── IP Perangkat (Management Network) ────────────
MAIN_ROUTER_IP=192.168.99.1
ROUTER_KANTOR_IP=192.168.99.3
OPENWRT_IP=192.168.99.4

# ── SSH Credentials ───────────────────────────────
# MikroTik CHR — default kosong
MAIN_ROUTER_SSH_USER=admin
MAIN_ROUTER_SSH_PASS=

ROUTER_KANTOR_SSH_USER=admin
ROUTER_KANTOR_SSH_PASS=

# OpenWRT — sesuai password yang di-set via passwd root
OPENWRT_SSH_USER=root
OPENWRT_SSH_PASS=password_openwrt

# ── Polling Interval (detik) ──────────────────────
PING_INTERVAL=30
SNMP_INTERVAL=60
BANDWIDTH_INTERVAL=60

# ── Supabase Backup ───────────────────────────────
SUPABASE_URL=https://xxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=your_service_role_key

# ── FastAPI Server ────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
```

### 2. Init Database

```bash
source venv/bin/activate
python3 -c "from models.database import init_db; init_db()"
# Output: [DB] Tabel berhasil dibuat/diverifikasi
```

---

## Menjalankan Program

> Semua perintah dijalankan dari direktori `~/monitoring`
> dengan virtual environment aktif (`source venv/bin/activate`)

### Monitoring Scheduler (main.py)

Scheduler utama yang menjalankan polling ping, SNMP, bandwidth,
dan backup Supabase secara otomatis.

```bash
cd ~/monitoring
source venv/bin/activate
python3 main.py
```

Output normal:

```
[INFO] main — ==============================
[INFO] main —   Network Monitoring Starting
[INFO] main — ==============================
[DB] Tabel berhasil dibuat/diverifikasi
[INFO] ping_monitor  — main-router (192.168.99.1) — UP | latency: 1.15 ms
[INFO] ping_monitor  — router-kantor (192.168.99.3) — UP | latency: 1.008 ms
[INFO] ping_monitor  — openwrt (192.168.99.4) — UP | latency: 1.727 ms
[INFO] snmp_collector — main-router | sysName: main-router
[INFO] snmp_collector — main-router | totalInterfaces: 5
[INFO] bandwidth     — main-router | [2] ether1 in:80705689 out:8363311
[INFO] main — Scheduler aktif — ping:30s | snmp:60s | bw:60s
[INFO] main — Backup scheduler aktif — interval: 60 menit
```

> `main.py` berjalan terus di foreground. Gunakan `Ctrl+C` untuk stop,
> atau jalankan di background dengan `nohup python3 main.py &`.

---

### API Server (api/run_api.py)

FastAPI server untuk endpoint reboot, ping now, dan status.
Jalankan di **terminal terpisah**.

```bash
cd ~/monitoring
source venv/bin/activate
python3 api/run_api.py
```

Output normal:

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Akses dokumentasi API otomatis di browser:

```
http://192.168.99.2:8000/docs        # lokal
https://monitoring.domain.com/docs   # via Cloudflare Tunnel
```

---

### Menu CLI (menu.py)

Menu interaktif untuk monitoring, export data, dan backup manual.
Jalankan di **terminal terpisah** — tidak mengganggu `main.py`.

```bash
cd ~/monitoring
source venv/bin/activate
python3 menu.py
```

Tampilan menu:

```
====================================================
     NETWORK MONITORING — MENU UTAMA
====================================================
  Waktu : 2026-04-27 16:06:41
====================================================
  [1] Status perangkat (realtime)
  [2] Lihat log lokal
  [3] Lihat backup Supabase
  [4] Backup manual ke Supabase
  [5] Statistik database
  [6] Export data ke CSV
  [0] Keluar
====================================================
Pilih menu:
```

> Menu tidak membutuhkan `sudo`. Keluar dari menu tidak menghentikan
> `main.py` yang berjalan di terminal lain.

---

## API Endpoints

Base URL: `http://192.168.99.2:8000` atau `https://monitoring.domain.com`

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/` | Info service & status |
| GET | `/devices` | Daftar semua device |
| GET | `/status` | Status terbaru semua device |
| GET | `/status/{device}` | Status terbaru satu device |
| POST | `/ping` | Ping manual ke device |
| POST | `/reboot` | Reboot device via SSH |

### Contoh Request

**GET /status**
```bash
curl https://monitoring.domain.com/status
```

Response:
```json
{
  "status": "ok",
  "data": [
    {
      "device": "main-router",
      "ip_address": "192.168.99.1",
      "status": "up",
      "latency_ms": 0.98,
      "checked_at": "2026-04-28T20:18:24"
    }
  ]
}
```

**POST /ping**
```bash
curl -X POST https://monitoring.domain.com/ping \
     -H "Content-Type: application/json" \
     -d '{"device": "main-router"}'
```

Response:
```json
{
  "status": "ok",
  "device": "main-router",
  "ip_address": "192.168.99.1",
  "ping_result": "up",
  "latency_ms": 0.794,
  "checked_at": "2026-04-28T20:20:15"
}
```

**POST /reboot**
```bash
curl -X POST https://monitoring.domain.com/reboot \
     -H "Content-Type: application/json" \
     -d '{"device": "openwrt"}'
```

Response:
```json
{
  "status": "ok",
  "device": "openwrt",
  "message": "Reboot command berhasil dikirim ke openwrt",
  "note": "Device akan restart dalam beberapa detik",
  "sent_at": "2026-04-28T20:25:00"
}
```

### Contoh dari Laravel

```php
use Illuminate\Support\Facades\Http;

$base = 'https://monitoring.domain.com';

// Status semua device
$status = Http::get("{$base}/status")->json();

// Ping manual
$ping = Http::post("{$base}/ping", [
    'device' => 'main-router'
])->json();

// Reboot device
$reboot = Http::post("{$base}/reboot", [
    'device' => 'openwrt'
])->json();
```

---

## Menu CLI

### [1] Status Perangkat

Menampilkan status UP/DOWN dan latency terbaru per perangkat
dari database lokal.

```
====================================================
  STATUS PERANGKAT — REALTIME
====================================================
Perangkat         IP                Status    Latency
----------------  ----------------  --------  --------
main-router       192.168.99.1      ✓ UP      0.98 ms
router-kantor     192.168.99.3      ✓ UP      0.885 ms
openwrt           192.168.99.4      ✓ UP      0.868 ms
```

### [2] Log Lokal

Lihat 20 data terbaru dari MariaDB.
Sub-menu: Device Status / SNMP Metrics / Interface Traffic.

### [3] Backup Supabase

Lihat 20 data terbaru dari Supabase (histori backup).
Sub-menu: Device Status / SNMP Metrics / Interface Traffic.

### [4] Backup Manual

Jalankan backup + cleanup sekarang tanpa menunggu scheduler 60 menit.

### [5] Statistik Database

```
DATABASE LOKAL (MariaDB)
Tabel                 Total Row   Retain Max    Penuh (%)
--------------------  ----------  ------------  ----------
device_status         850         1200          70.8%
snmp_metrics          2100        3500          60.0%
interface_traffic     1200        2500          48.0%

Data terlama : 2026-04-28 18:00:00
Data terbaru : 2026-04-28 21:00:00

DATABASE BACKUP (Supabase)
device_status_backup                1828 records
snmp_metrics_backup                 6543 records
interface_traffic_backup            4320 records
```

### [6] Export CSV

Export data ke file CSV di folder `~/monitoring/exports/`.
Pilih sumber (lokal/Supabase) dan tipe data.

```
exports/
  device_status_20260428_210000.csv
  snmp_metrics_20260428_210000.csv
  interface_traffic_20260428_210000.csv
```

---

## Backup Supabase

Backup berjalan otomatis setiap **60 menit** via scheduler di `main.py`.

### Skema Retention (Offset-based)

Data tidak dihapus berdasarkan waktu, melainkan berdasarkan
jumlah row agar data tidak hilang saat perangkat down lama.

| Tabel | Retain Lokal | Keterangan |
|-------|-------------|------------|
| device_status | 1200 row | ~3 jam data |
| snmp_metrics | 3500 row | ~3 jam data |
| interface_traffic | 2500 row | ~3 jam data |

### Estimasi Storage Supabase

| Periode | Storage | Records |
|---------|---------|---------|
| Per jam | ~342 KB | ~2160 records |
| Per hari | ~8 MB | ~51840 records |
| Per bulan | ~240 MB | ~1.5 juta records |
| Free tier (500 MB) | ~2 bulan | — |

### Backup Manual

```bash
source venv/bin/activate
python3 -c "from backup.supabase_backup import run; run()"
```

---

## Troubleshooting

### icmplib error: permission denied

```bash
# Set capability raw socket
sudo setcap cap_net_raw+ep ~/monitoring/venv/bin/python3

# Verifikasi
getcap ~/monitoring/venv/bin/python3
```

### ModuleNotFoundError saat pakai sudo

```bash
# Jangan pakai sudo python3, tapi:
sudo ~/monitoring/venv/bin/python3 main.py

# Atau gunakan setcap agar tidak perlu sudo sama sekali
sudo setcap cap_net_raw+ep ~/monitoring/venv/bin/python3
python3 main.py  # tanpa sudo
```

### SNMP timeout ke openWRT

```bash
# Pastikan snmpd jalan di openWRT
/etc/init.d/snmpd status

# Restart kalau perlu
/etc/init.d/snmpd restart

# Test dari server
snmpwalk -v2c -c public 192.168.99.4 1.3.6.1.2.1.1
```

### SSH Authentication Failed (reboot endpoint)

```bash
# Test SSH manual dulu
ssh admin@192.168.99.1   # MikroTik
ssh root@192.168.99.4    # OpenWRT

# Pastikan .env sudah benar dan API sudah direstart
pkill -f run_api.py
python3 api/run_api.py
```

### easysnmp hanya return 1 interface

Interface index diambil dari `item.oid` bukan `item.oid_index`
karena easysnmp versi ini return `oid_index` kosong.
Sudah di-handle di `collectors/bandwidth.py` via:

```python
idx = str(item.oid).strip().split('.')[-1]
```

### Database lokal kosong setelah backup

Normal jika semua data sudah lebih tua dari threshold retain.
Jalankan `main.py` dan tunggu beberapa menit hingga data baru masuk.

---

## Catatan Penting

- Gunakan `enp0s3` bukan `eth0` di `/etc/network/interfaces` pada Debian VirtualBox
- OpenWRT 25.12 menggunakan `apk` (bukan `opkg`) dan `nftables` (bukan `iptables`)
- File `.env` **jangan pernah** di-commit ke GitHub
- `setcap` perlu diulang jika Python di-upgrade atau venv di-recreate
- `menu.py` dan `api/run_api.py` dijalankan di terminal terpisah dari `main.py`