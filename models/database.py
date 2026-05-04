import os
import pymysql
#from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, TinyInteger
from sqlalchemy import create_engine, Column, Integer, SmallInteger, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = (
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Device(Base):
    """Daftar device yang akan dimonitor — dynamic dari DB"""
    __tablename__ = 'devices'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    name           = Column(String(50), nullable=False, unique=True)
    ip_address     = Column(String(20), nullable=False)
    type           = Column(String(20), nullable=False)  # mikrotik / openwrt / linux
    ssh_user       = Column(String(50), default='admin')
    ssh_pass       = Column(String(100), default='')
    snmp_community = Column(String(20), default='public')
    is_active = Column(Integer, default=1)  # 1=aktif, 0=nonaktif
    description    = Column(String(100), default='')
    created_at     = Column(DateTime, default=datetime.now)
    updated_at     = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DeviceStatus(Base):
    """Status up/down dan latency setiap perangkat"""
    __tablename__ = 'device_status'

    id         = Column(Integer, primary_key=True, autoincrement=True)
    device     = Column(String(50), nullable=False)
    ip_address = Column(String(20), nullable=False)
    status     = Column(String(10), nullable=False)
    latency_ms = Column(Float, nullable=True)
    checked_at = Column(DateTime, default=datetime.now)


class SnmpMetric(Base):
    """Data SNMP dari setiap perangkat"""
    __tablename__ = 'snmp_metrics'

    id           = Column(Integer, primary_key=True, autoincrement=True)
    device       = Column(String(50), nullable=False)
    ip_address   = Column(String(20), nullable=False)
    metric_name  = Column(String(100), nullable=False)
    metric_value = Column(Text, nullable=True)
    collected_at = Column(DateTime, default=datetime.now)


class InterfaceTraffic(Base):
    """Traffic per interface"""
    __tablename__ = 'interface_traffic'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    device         = Column(String(50), nullable=False)
    ip_address     = Column(String(20), nullable=False)
    interface_name = Column(String(50), nullable=False)
    bytes_in       = Column(Integer, default=0)
    bytes_out      = Column(Integer, default=0)
    packets_in     = Column(Integer, default=0)
    packets_out    = Column(Integer, default=0)
    collected_at   = Column(DateTime, default=datetime.now)


def init_db():
    Base.metadata.create_all(bind=engine)
    print("[DB] Tabel berhasil dibuat/diverifikasi")


def get_session():
    return SessionLocal()


def get_active_devices() -> list:
    """
    Ambil semua device aktif dari DB.
    Dipanggil setiap siklus polling agar perubahan device langsung efektif.
    """
    session = get_session()
    try:
        devices = session.query(Device).filter(Device.is_active == 1).all()
        # Detach dari session agar bisa dipakai di luar
        result = []
        for d in devices:
            result.append({
                'id':             d.id,
                'name':           d.name,
                'ip_address':     d.ip_address,
                'type':           d.type,
                'ssh_user':       d.ssh_user,
                'ssh_pass':       d.ssh_pass,
                'snmp_community': d.snmp_community,
                'description':    d.description,
            })
        return result
    finally:
        session.close()


def is_db_alive() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False