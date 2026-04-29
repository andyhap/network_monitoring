import os
from datetime import datetime
from easysnmp import Session, EasySNMPError
from dotenv import load_dotenv
from models.database import get_session, InterfaceTraffic
from utils.logger import get_logger

load_dotenv()
logger = get_logger('bandwidth')

COMMUNITY = os.getenv('SNMP_COMMUNITY', 'public')
PORT      = int(os.getenv('SNMP_PORT', 161))

DEVICES = {
    'main-router':   os.getenv('MAIN_ROUTER_IP'),
    'router-kantor': os.getenv('ROUTER_KANTOR_IP'),
    'openwrt':       os.getenv('OPENWRT_IP'),
    'router-test':     os.getenv('ROUTER_TEST_IP'),
}

# OID tabel interface
OID_IF_NAME    = '1.3.6.1.2.1.2.2.1.2'   # ifDescr
OID_IF_IN_OCT  = '1.3.6.1.2.1.2.2.1.10'  # ifInOctets
OID_IF_OUT_OCT = '1.3.6.1.2.1.2.2.1.16'  # ifOutOctets
OID_IF_IN_PKT  = '1.3.6.1.2.1.2.2.1.11'  # ifInUcastPkts
OID_IF_OUT_PKT = '1.3.6.1.2.1.2.2.1.17'  # ifOutUcastPkts

def safe_int(value):
    """Konversi value ke int, return 0 jika gagal"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

def walk_to_dict(session, oid):
    """
    Walk OID dan return dict {index: value}
    index diambil dari angka terakhir di item.oid
    karena oid_index selalu kosong di versi easysnmp ini
    """
    result = {}
    try:
        items = session.walk(oid)
        for item in items:
            # Ambil angka terakhir dari oid
            # contoh: iso.3.6.1.2.1.2.2.1.2.3 → '3'
            idx = str(item.oid).strip().split('.')[-1]
            result[idx] = item.value
    except EasySNMPError as e:
        logger.warning(f"Walk error pada OID {oid}: {e}")
    return result

def poll_device(name: str, ip: str):
    try:
        snmp_session = Session(
            hostname=ip,
            community=COMMUNITY,
            version=2,
            remote_port=PORT,
            timeout=5,
            retries=2
        )

        # Ambil semua data sekaligus
        names   = walk_to_dict(snmp_session, OID_IF_NAME)
        in_oct  = walk_to_dict(snmp_session, OID_IF_IN_OCT)
        out_oct = walk_to_dict(snmp_session, OID_IF_OUT_OCT)
        in_pkt  = walk_to_dict(snmp_session, OID_IF_IN_PKT)
        out_pkt = walk_to_dict(snmp_session, OID_IF_OUT_PKT)

        if not names:
            logger.warning(f"{name} ({ip}) — tidak ada interface ditemukan via SNMP")
            return

        db_session = get_session()
        saved = 0

        for idx, iface_name in names.items():
            # Skip interface loopback
            if iface_name.lower() in ('lo', 'loopback'):
                continue

            b_in   = safe_int(in_oct.get(idx, 0))
            b_out  = safe_int(out_oct.get(idx, 0))
            p_in   = safe_int(in_pkt.get(idx, 0))
            p_out  = safe_int(out_pkt.get(idx, 0))

            logger.info(
                f"{name} | [{idx}] {iface_name} "
                f"in:{b_in} out:{b_out} "
                f"pkts_in:{p_in} pkts_out:{p_out}"
            )

            db_session.add(InterfaceTraffic(
                device=name,
                ip_address=ip,
                interface_name=iface_name,
                bytes_in=b_in,
                bytes_out=b_out,
                packets_in=p_in,
                packets_out=p_out,
                collected_at=datetime.now()
            ))
            saved += 1

        db_session.commit()
        db_session.close()
        logger.info(f"{name} — {saved} interface berhasil disimpan")

    except Exception as e:
        logger.error(f"Bandwidth error pada {name} ({ip}): {e}")

def run():
    logger.info("=== Bandwidth Monitor mulai ===")
    for name, ip in DEVICES.items():
        poll_device(name, ip)