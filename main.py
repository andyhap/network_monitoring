import uvicorn
import schedule
import threading
import time
import os
from dotenv import load_dotenv
from models.database import init_db
from backup import supabase_backup
from utils.logger import get_logger

load_dotenv()
logger = get_logger('main')


def _run_backup_scheduler():
    schedule.every(60).minutes.do(supabase_backup.run)
    logger.info("Backup scheduler aktif — interval: 60 menit")
    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    logger.info("==========================================")
    logger.info("  Network Monitoring — WebSocket Server   ")
    logger.info("==========================================")

    init_db()

    # Backup Supabase jalan di background thread (tidak blokir uvicorn)
    threading.Thread(target=_run_backup_scheduler, daemon=True).start()

    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', 8000))

    logger.info(f"WebSocket Server : ws://{host}:{port}/ws")
    logger.info(f"REST API         : http://{host}:{port}")

    uvicorn.run("api.main_api:app", host=host, port=port, reload=False, log_level="info")


if __name__ == '__main__':
    main()
