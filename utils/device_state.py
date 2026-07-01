"""
Shared in-memory state yang di-update oleh ping_monitor
dan dibaca oleh snmp_collector serta bandwidth.

Schedule library berjalan single-threaded, jadi tidak butuh lock.
"""

_status: dict[str, bool] = {}  # {device_name: is_up}
_recovery_pending: bool = False


def update(device: str, is_up: bool) -> None:
    _status[device] = is_up


def mark_recovery() -> None:
    """Dipanggil oleh ping_monitor saat transisi all_down → ada yang UP."""
    global _recovery_pending
    _recovery_pending = True


def consume_recovery() -> bool:
    """Return True sekali saat baru recovery, lalu reset. Dipanggil di main loop."""
    global _recovery_pending
    if _recovery_pending:
        _recovery_pending = False
        return True
    return False


def is_up(device: str) -> bool:
    # Default True supaya kolektor tetap jalan sebelum ping pertama
    return _status.get(device, True)


def all_down() -> bool:
    """True jika semua device sudah di-ping dan semuanya down."""
    if not _status:
        return False
    return not any(_status.values())


def any_up() -> bool:
    return any(_status.values())


def summary() -> str:
    up   = [d for d, v in _status.items() if v]
    down = [d for d, v in _status.items() if not v]
    return f"UP={up} DOWN={down}"
