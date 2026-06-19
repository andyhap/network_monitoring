from datetime import datetime
from easysnmp import Session, EasySNMPError
from models.database import get_session, InterfaceTraffic, get_active_devices
from utils.logger import get_logger
from utils import device_state

logger = get_logger('bandwidth')

OID_IF_NAME    = '1.3.6.1.2.1.2.2.1.2'
OID_IF_IN_OCT  = '1.3.6.1.2.1.2.2.1.10'
OID_IF_OUT_OCT = '1.3.6.1.2.1.2.2.1.16'
OID_IF_IN_PKT  = '1.3.6.1.2.1.2.2.1.11'
OID_IF_OUT_PKT = '1.3.6.1.2.1.2.2.1.17'


def safe_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def walk_to_dict(session, oid):
    result = {}
    try:
        items = session.walk(oid)
        for item in items:
            idx = str(item.oid).strip().split('.')[-1]
            result[idx] = item.value
    except EasySNMPError as e:
        logger.warning(f"Walk error pada OID {oid}: {e}")
    return result


def poll_device(device: dict):
    name      = device['name']
    ip        = device['ip_address']
    community = device['snmp_community']

    # Skip device yang diketahui down dari hasil ping terakhir
    if not device_state.is_up(name):
        logger.warning(f"{name} ({ip}) — DOWN (ping), Bandwidth dilewati")
        return

    try:
        # timeout=2, retries=1 → maks 4s per walk (vs 15s sebelumnya)
        snmp_session = Session(
            hostname=ip, community=community,
            version=2, remote_port=161,
            timeout=2, retries=1
        )

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
            if iface_name.lower() in ('lo', 'loopback'):
                continue

            b_in  = safe_int(in_oct.get(idx, 0))
            b_out = safe_int(out_oct.get(idx, 0))
            p_in  = safe_int(in_pkt.get(idx, 0))
            p_out = safe_int(out_pkt.get(idx, 0))

            logger.info(f"{name} | [{idx}] {iface_name} in:{b_in} out:{b_out}")

            db_session.add(InterfaceTraffic(
                device=name, ip_address=ip,
                interface_name=iface_name,
                bytes_in=b_in, bytes_out=b_out,
                packets_in=p_in, packets_out=p_out,
                collected_at=datetime.now()
            ))
            saved += 1

        db_session.commit()
        db_session.close()
        logger.info(f"{name} — {saved} interface berhasil disimpan")

    except Exception as e:
        logger.error(f"Bandwidth error pada {name} ({ip}): {e}")


def run():
    # Jika semua device down → pause total agar log tidak membengkak
    if device_state.all_down():
        logger.warning("=== Bandwidth Monitor PAUSE — semua device DOWN ===")
        return

    logger.info("=== Bandwidth Monitor mulai ===")
    devices = get_active_devices()
    if not devices:
        logger.warning("Tidak ada device aktif di database")
        return
    for device in devices:
        poll_device(device)