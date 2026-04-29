import os
import json
from datetime import datetime
from utils.logger import get_logger

logger = get_logger('buffer')

BUFFER_DIR = os.path.join(os.path.dirname(__file__), '..', 'buffer_data')


def _ensure_dir():
    os.makedirs(BUFFER_DIR, exist_ok=True)


def save(table: str, data: dict):
    """Simpan satu record ke buffer file JSON saat DB down"""
    _ensure_dir()
    path = os.path.join(BUFFER_DIR, f"{table}.jsonl")
    try:
        with open(path, 'a') as f:
            f.write(json.dumps(data) + '\n')
    except Exception as e:
        logger.error(f"Gagal simpan buffer {table}: {e}")


def flush(table: str, model_class, session, field_map: dict) -> int:
    """
    Flush buffer ke DB saat DB sudah nyala lagi.
    field_map: mapping key JSON ke attribute model
    Return: jumlah record yang berhasil di-flush
    """
    _ensure_dir()
    path = os.path.join(BUFFER_DIR, f"{table}.jsonl")

    if not os.path.exists(path):
        return 0

    flushed = 0
    failed_lines = []

    try:
        with open(path, 'r') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                obj = model_class()
                for json_key, model_attr in field_map.items():
                    val = data.get(json_key)
                    # Parse datetime string kembali ke datetime object
                    if isinstance(val, str) and 'T' in val:
                        try:
                            val = datetime.fromisoformat(val)
                        except ValueError:
                            pass
                    setattr(obj, model_attr, val)
                session.add(obj)
                flushed += 1
            except Exception as e:
                logger.warning(f"Gagal parse buffer line: {e}")
                failed_lines.append(line)

        session.commit()

        # Tulis ulang hanya yang gagal (kalau ada)
        with open(path, 'w') as f:
            for line in failed_lines:
                f.write(line + '\n')

        if flushed > 0:
            logger.info(f"Buffer flush {table}: {flushed} records ke DB")

        return flushed

    except Exception as e:
        session.rollback()
        logger.error(f"Gagal flush buffer {table}: {e}")
        return 0


def count(table: str) -> int:
    """Hitung jumlah record yang ada di buffer"""
    path = os.path.join(BUFFER_DIR, f"{table}.jsonl")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, 'r') as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def has_data() -> bool:
    """Cek apakah ada buffer yang belum di-flush"""
    _ensure_dir()
    for fname in os.listdir(BUFFER_DIR):
        if fname.endswith('.jsonl') and count(fname.replace('.jsonl', '')) > 0:
            return True
    return False