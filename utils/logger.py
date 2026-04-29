import logging
import os
from datetime import datetime

def get_logger(name: str) -> logging.Logger:
    os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'logs'), exist_ok=True)
    log_path = os.path.join(os.path.dirname(__file__), '..', 'logs', 'monitor.log')

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s — %(message)s',
                                      datefmt='%Y-%m-%d %H:%M:%S')
        fh = logging.FileHandler(log_path)
        fh.setFormatter(formatter)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger