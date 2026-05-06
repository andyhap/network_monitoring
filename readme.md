# 🖥️ Network Monitoring — Python

Sistem monitoring jaringan berbasis Python untuk simulasi jaringan menggunakan GNS3 + VirtualBox. Memonitor status perangkat, traffic bandwidth, dan metrics SNMP secara realtime dengan manajemen device dinamis dari database dan backup otomatis ke Supabase.

---

## 📋 Daftar Isi

- [Arsitektur](#arsitektur)
- [Stack & Library](#stack--library)
- [Persyaratan Sistem](#persyaratan-sistem)
- [Struktur Project](#struktur-project)
- [Instalasi](#instalasi)
- [Konfigurasi](#konfigurasi)
- [Migrasi Database](#migrasi-database)
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
        ├── GET  /status              → status semua device
        ├── POST /ping                → ping manual
        ├── POST /reboot              → reboot device via SSH
        ├── GET  /api/devices         → list device dari DB
        ├── POST /api/devices         → tambah device baru
        ├── PUT  /api/devices/{id}    → update device
        ├── PATCH /api/devices/{id}/toggle → aktif/nonaktif
        ├── DELETE /api/devices/{id}  → hapus + archive ke Supabase
        └── POST /api/backup/manual   → trigger backup ke Supabase

Server Debian (GNS3)
    ├── main.py       → polling SNMP, ping, bandwidth (scheduler)
    ├── menu.py       → CLI menu monitoring & manajemen device
    ├── migrate.py    → setup schema & seed device ke database
    ├── test_api.py   → test semua endpoint API via CLI
    ├── api/          → FastAPI server
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
├── menu.py                   # CLI menu + manajemen device
├── migrate.py                # setup schema & seed device dari .env
├── test_api.py               # test semua endpoint API via CLI
├── requirements.txt
├── api/
│   ├── __init__.py
│   ├── main_api.py           # FastAPI endpoints
│   └── run_api.py            # entry point API server
├── backup/
│   ├── __init__.py
│   └── supabase_backup.py    # backup offset-based & cleanup
├── collectors/
│   ├── __init__.py
│   ├── bandwidth.py          # traffic per interface via SNMP
│   ├── ping_monitor.py       # status, latency, packet_loss
│   └── snmp_collector.py     # SNMP metrics + macAddress + monitoringInterval
├── models/
│   ├── __init__.py
│   └── database.py           # schema, koneksi DB, get_active_devices()
├── utils/
│   ├── __init__.py
│   └── logger.py             # logging ke file & terminal
├── logs/                     # tidak di-commit
└── exports/                  # hasil export CSV, tidak di-commit
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
sudo apt install -y python3-pip python3-venv python3-dev
sudo apt install -y mariadb-server mariadb-client
sudo apt install -y libsnmp-dev snmp snmp-mibs-downloader
sudo apt install -y gcc build-essential
```

### 3. Nonaktifkan APIPA (Khusus VirtualBox)

```bash
sudo nano /etc/sysctl.d/no-apipa.conf
```

Isi dengan:

```
net.ipv4.conf.all.autoconf = 0
net.ipv4.conf.default.autoconf = 0
```

```bash
sudo sysctl --system
```

### 4. Setup MariaDB

```bash
sudo mysql_secure_installation
sudo mysql -u root -p
```

```sql
CREATE DATABASE monitoring_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'monitor_user'@'localhost' IDENTIFIED BY 'ganti_password_ini';
GRANT ALL PRIVILEGES ON monitoring_db.* TO 'monitor_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 5. Virtual Environment & Library

```bash
cd ~/monitoring
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 6. Setup Capability untuk icmplib

```bash
sudo setcap cap_net_raw+ep ~/monitoring/venv/bin/python3

# Verifikasi
getcap ~/monitoring/venv/bin/python3
# Output: .../python3 cap_net_raw+ep
```

> **Penting:** Ulangi `setcap` jika Python di-upgrade atau venv di-recreate.

### 7. Setup Tabel Supabase

Masuk ke **Supabase Dashboard → SQL Editor**, jalankan:

```sql
-- Backup tables
CREATE TABLE device_status_backup (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, status VARCHAR(10) NOT NULL,
    latency_ms FLOAT, checked_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE snmp_metrics_backup (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, metric_name VARCHAR(100) NOT NULL,
    metric_value TEXT, collected_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE interface_traffic_backup (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, interface_name VARCHAR(50) NOT NULL,
    bytes_in BIGINT DEFAULT 0, bytes_out BIGINT DEFAULT 0,
    packets_in BIGINT DEFAULT 0, packets_out BIGINT DEFAULT 0,
    collected_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Archive tables (data device yang dihapus)
CREATE TABLE deleted_device_status (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, status VARCHAR(10) NOT NULL,
    latency_ms FLOAT, checked_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ DEFAULT NOW(), device_info JSONB
);
CREATE TABLE deleted_snmp_metrics (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, metric_name VARCHAR(100) NOT NULL,
    metric_value TEXT, collected_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ DEFAULT NOW(), device_info JSONB
);
CREATE TABLE deleted_interface_traffic (
    id BIGSERIAL PRIMARY KEY, device VARCHAR(50) NOT NULL,
    ip_address VARCHAR(20) NOT NULL, interface_name VARCHAR(50) NOT NULL,
    bytes_in BIGINT DEFAULT 0, bytes_out BIGINT DEFAULT 0,
    packets_in BIGINT DEFAULT 0, packets_out BIGINT DEFAULT 0,
    collected_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ DEFAULT NOW(), device_info JSONB
);

-- Indexes
CREATE INDEX idx_ds  ON device_status_backup     (device, checked_at DESC);
CREATE INDEX idx_sm  ON snmp_metrics_backup      (device, collected_at DESC);
CREATE INDEX idx_it  ON interface_traffic_backup (device, collected_at DESC);
CREATE INDEX idx_dds ON deleted_device_status    (device, checked_at DESC);
CREATE INDEX idx_dsm ON deleted_snmp_metrics     (device, collected_at DESC);
CREATE INDEX idx_dit ON deleted_interface_traffic(device, collected_at DESC);
```

---

## Konfigurasi

### File .env

```bash
cp .env.example .env
nano .env
```

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_NAME=monitoring_db
DB_USER=monitor_user
DB_PASS=ganti_password_ini

# SNMP
SNMP_COMMUNITY=public
SNMP_PORT=161

# Polling Interval (detik)
PING_INTERVAL=30
SNMP_INTERVAL=60
BANDWIDTH_INTERVAL=60

# Supabase Backup
SUPABASE_URL=https://xxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=your_service_role_key

# FastAPI
API_HOST=0.0.0.0
API_PORT=8000
```

> **Catatan:** IP dan SSH credentials device **tidak lagi** disimpan di `.env`.
> Semua data device dikelola dari database via menu CLI atau API.

---

## Migrasi Database

Jalankan sekali setelah setup untuk membuat semua tabel dan seed device awal:

```bash
cd ~/monitoring
source venv/bin/activate
python3 migrate.py
```

Output normal:

```
==================================================
  DATABASE MIGRATION
==================================================
[1/3] Membuat tabel...         [DB] Tabel berhasil dibuat/diverifikasi
[2/3] Verifikasi tabel devices... Tabel 'devices' sudah ada.
[3/3] Cek data device...       Sudah ada 4 device, skip seed.
==================================================
  MIGRASI SELESAI
==================================================
  [1] main-router      192.168.99.1  mikrotik  AKTIF
  [2] router-kantor    192.168.99.3  mikrotik  AKTIF
  [3] openwrt          192.168.99.4  openwrt   AKTIF
  [4] router-test      192.168.99.5  mikrotik  AKTIF
```

### Schema Tabel devices

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INT AUTO_INCREMENT | Primary key |
| name | VARCHAR(50) UNIQUE | Nama unik device |
| ip_address | VARCHAR(20) | IP management network |
| type | VARCHAR(20) | mikrotik / openwrt / linux |
| ssh_user | VARCHAR(50) | Username SSH |
| ssh_pass | VARCHAR(100) | Password SSH |
| snmp_community | VARCHAR(20) | SNMP community string |
| is_active | INT | 1=aktif, 0=nonaktif |
| description | VARCHAR(100) | Deskripsi opsional |
| created_at | DATETIME | Waktu dibuat |
| updated_at | DATETIME | Waktu terakhir diubah |

---

## Menjalankan Program

> Jalankan dari `~/monitoring` dengan venv aktif.
> Masing-masing program di terminal terpisah.

```bash
# Terminal 1 — Monitoring scheduler
source venv/bin/activate && python3 main.py

# Terminal 2 — API server
source venv/bin/activate && python3 api/run_api.py

# Terminal 3 — Menu CLI (opsional)
source venv/bin/activate && python3 menu.py

# Terminal 4 — Test API (opsional)
source venv/bin/activate && python3 test_api.py
```

Swagger UI: `https://monitoring.domain.com/docs`

---

## API Endpoints

Base URL: `https://monitoring.domain.com`

### Status & Aksi

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/` | Health check |
| GET | `/status` | Status terbaru semua device |
| GET | `/status/{device}` | Status terbaru satu device |
| POST | `/ping` | Ping manual → simpan ke DB |
| POST | `/reboot` | Reboot device via SSH |

### Device Management

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/api/devices` | List semua device |
| POST | `/api/devices` | Tambah device baru |
| PUT | `/api/devices/{id}` | Update detail device |
| PATCH | `/api/devices/{id}/toggle` | Toggle aktif/nonaktif |
| DELETE | `/api/devices/{id}` | Hapus + archive ke Supabase |
| DELETE | `/api/devices/cleanup/orphan` | Bersihkan data device orphan |

### Backup

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| POST | `/api/backup/manual` | Trigger backup ke Supabase (background) |

---

### Contoh Request

**POST /api/devices — Tambah device**
```bash
curl -X POST https://monitoring.domain.com/api/devices \
     -H "Content-Type: application/json" \
     -d '{
       "name": "router-baru",
       "ip_address": "192.168.99.10",
       "type": "mikrotik",
       "ssh_user": "admin",
       "ssh_pass": "",
       "snmp_community": "public",
       "description": "Router lantai 2"
     }'
```
```json
{ "status": "ok", "message": "Device 'router-baru' berhasil ditambahkan", "id": 5 }
```

**DELETE /api/devices/{id} — Hapus + archive**
```bash
curl -X DELETE https://monitoring.domain.com/api/devices/5
```
```json
{
  "status": "ok",
  "message": "Device 'router-baru' berhasil dihapus beserta semua datanya",
  "archived": { "device_status": 48, "snmp_metrics": 288, "interface_traffic": 192 },
  "deleted_from_local": { "device_status": 48, "snmp_metrics": 288, "interface_traffic": 192 }
}
```

**POST /api/backup/manual — Trigger backup**
```bash
curl -X POST https://monitoring.domain.com/api/backup/manual
```
```json
{
  "status": "accepted",
  "message": "Backup akan dilakukan di background. Cek log untuk hasilnya.",
  "timestamp": "2026-05-04T12:00:00"
}
```

> Endpoint backup return `accepted` langsung — proses berjalan di background.
> Cek progress: `tail -f ~/monitoring/logs/api.log | grep backup`

### Dari Laravel

```php
$base = config('services.monitoring.url');

// Tambah device
Http::post("{$base}/api/devices", [
    'name' => 'router-baru', 'ip_address' => '192.168.99.10',
    'type' => 'mikrotik', 'ssh_user' => 'admin',
    'ssh_pass' => '', 'snmp_community' => 'public',
])->json();

// Hapus device (archive otomatis ke Supabase)
Http::delete("{$base}/api/devices/5")->json();

// Trigger backup manual
Http::post("{$base}/api/backup/manual")->json();
```

---

## Menu CLI

```
====================================================
     NETWORK MONITORING — MENU UTAMA
====================================================
  [1] Status perangkat (realtime)
  [2] Lihat log lokal
  [3] Lihat backup Supabase
  [4] Backup manual ke Supabase
  [5] Statistik database
  [6] Export data ke CSV
  [7] Manajemen device
  [0] Keluar
====================================================
```

### Menu [7] Manajemen Device

```
  [1] Lihat semua device
  [2] Tambah device baru
  [3] Toggle aktif / nonaktif
  [4] Hapus device permanen (archive ke Supabase)
```

Perubahan device langsung efektif pada siklus berikutnya — tidak perlu restart `main.py`.

---

## Backup Supabase

### Skema Offset-Based Retention

Data dihapus berdasarkan jumlah row, bukan waktu. Mencegah data hilang saat device down lama.

| Tabel | Retain Lokal | Coverage |
|-------|-------------|----------|
| device_status | 1200 row | ~3 jam |
| snmp_metrics | 3500 row | ~3 jam |
| interface_traffic | 2500 row | ~3 jam |

### Archive Device Dihapus

Saat device dihapus, semua data monitoring otomatis di-archive ke tabel
`deleted_device_status`, `deleted_snmp_metrics`, `deleted_interface_traffic`
di Supabase sebelum dihapus dari database lokal.
Setiap record menyimpan `device_info` (JSON) sebagai referensi historis.

### Estimasi Storage

| Periode | Storage |
|---------|---------|
| Per hari | ~8 MB |
| Per bulan | ~240 MB |
| Free tier (500 MB) | ~2 bulan |

---

## Troubleshooting

**icmplib: permission denied**
```bash
sudo setcap cap_net_raw+ep ~/monitoring/venv/bin/python3
```

**ModuleNotFoundError saat pakai sudo**
```bash
sudo ~/monitoring/venv/bin/python3 main.py
```

**SNMP timeout ke openWRT**
```bash
/etc/init.d/snmpd restart
snmpwalk -v2c -c public 192.168.99.4 1.3.6.1.2.1.1
```

**SSH Authentication Failed**
```bash
ssh admin@192.168.99.1  # test koneksi manual
# Cek credentials di tabel devices via menu CLI [7][1]
```

**Device tidak termonitor setelah ditambah**

Normal — device baru mulai dimonitor pada siklus berikutnya (maks 30-60 detik). Tidak perlu restart `main.py`.

**Data orphan setelah hapus device lama**
```bash
curl -X DELETE https://monitoring.domain.com/api/devices/cleanup/orphan
```

**Backup tidak merespons**
```bash
tail -f ~/monitoring/logs/api.log | grep backup
```

---

## Catatan Penting

- OpenWRT 25.12: `apk` (bukan `opkg`), `nftables` (bukan `iptables`), editor `vi` (bukan `nano`)
- Perubahan device (tambah/hapus/toggle) **tidak perlu restart** `main.py`
- `setcap` perlu diulang jika Python di-upgrade atau venv di-recreate
