import schedule
import time
import os
from dotenv import load_dotenv
from models.database import init_db
from collectors import ping_monitor, snmp_collector, bandwidth
from utils.logger import get_logger
from backup import supabase_backup

load_dotenv()
logger = get_logger('main')

def main():
    logger.info("==============================")
    logger.info("  Network Monitoring Starting ")
    logger.info("==============================")

    # Inisialisasi database
    init_db()

    # Jalankan sekali langsung saat start
    ping_monitor.run()
    snmp_collector.run()
    bandwidth.run()

    # Schedule polling
    ping_interval = int(os.getenv('PING_INTERVAL', 30))
    snmp_interval = int(os.getenv('SNMP_INTERVAL', 60))
    bw_interval   = int(os.getenv('BANDWIDTH_INTERVAL', 60))

    schedule.every(ping_interval).seconds.do(ping_monitor.run)
    schedule.every(snmp_interval).seconds.do(snmp_collector.run)
    schedule.every(bw_interval).seconds.do(bandwidth.run)

    # Backup ke Supabase setiap 60 menit
    schedule.every(60).minutes.do(supabase_backup.run)
    logger.info("Backup scheduler aktif — interval: 60 menit")

    logger.info(f"Scheduler aktif — ping:{ping_interval}s | snmp:{snmp_interval}s | bw:{bw_interval}s")


    # Loop scheduler
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(1)

    # rolling backup ke Supabase 60 menit
    # backup_interval = 60  # setiap 60 menit
    # schedule.every(backup_interval).minutes.do(supabase_backup.run)
    # logger.info(f"Backup scheduler aktif — interval: {backup_interval} menit")

if __name__ == '__main__':
    main()