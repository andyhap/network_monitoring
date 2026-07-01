import schedule
import time
import os
from dotenv import load_dotenv
from collectors import ping_monitor, snmp_collector, bandwidth
from utils.logger import get_logger
from utils import ws_client, device_state

load_dotenv()
logger = get_logger('main')


def main():
    logger.info("==========================================")
    logger.info("  Network Monitoring — WebSocket Client   ")
    logger.info("==========================================")

    # Mulai WebSocket sender (background thread, reconnect otomatis)
    server_url = os.getenv('WS_SERVER_URL', 'ws://localhost:8000')
    ws_secret  = os.getenv('WS_SECRET', '')
    ws_client.start(server_url, ws_secret)

    # Tunggu koneksi WS sebelum polling pertama (maks 30 detik)
    logger.info("Menunggu koneksi ke WebSocket server...")
    if ws_client.wait_connected(timeout=30):
        logger.info("Terkoneksi — memulai polling pertama")
    else:
        logger.warning("Timeout 30s — collector akan mulai saat koneksi terbentuk")

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

    logger.info(f"Scheduler aktif — ping:{ping_interval}s | snmp:{snmp_interval}s | bw:{bw_interval}s")

    while True:
        try:
            schedule.run_pending()
            if device_state.consume_recovery():
                logger.info("[Recovery] Device UP setelah pause — trigger immediate SNMP & Bandwidth")
                snmp_collector.run()
                bandwidth.run()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        time.sleep(1)


if __name__ == '__main__':
    main()
