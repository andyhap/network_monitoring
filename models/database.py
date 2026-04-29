import os
import pymysql
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
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


class DeviceStatus(Base):
    """Status up/down dan latency setiap perangkat"""
    __tablename__ = 'device_status'

    id         = Column(Integer, primary_key=True, autoincrement=True)
    device     = Column(String(50), nullable=False)   # main-router, router-kantor, openwrt
    ip_address = Column(String(20), nullable=False)
    status     = Column(String(10), nullable=False)   # up / down
    latency_ms = Column(Float, nullable=True)
    checked_at = Column(DateTime, default=datetime.now)


class SnmpMetric(Base):
    """Data SNMP dari setiap perangkat"""
    __tablename__ = 'snmp_metrics'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    device         = Column(String(50), nullable=False)
    ip_address     = Column(String(20), nullable=False)
    metric_name    = Column(String(100), nullable=False)  # sysName, sysUpTime, dll
    metric_value   = Column(Text, nullable=True)
    collected_at   = Column(DateTime, default=datetime.now)


class InterfaceTraffic(Base):
    """Traffic per interface (bytes in/out)"""
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
    """Buat semua tabel jika belum ada"""
    Base.metadata.create_all(bind=engine)
    print("[DB] Tabel berhasil dibuat/diverifikasi")


def get_session():
    return SessionLocal()

def is_db_alive() -> bool:
    """Cek apakah koneksi ke MariaDB masih hidup"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False