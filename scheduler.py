import logging
import signal
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from db_connection import DBManager
from data_generator import DataGenerator
from db_pusher import DBPusher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SchedulerDaemon")

class CronSchedulerDaemon:
    def __init__(self, config_path="config.yaml"):
        self.db = DBManager(config_path)
        self.generator = DataGenerator(self.db)
        self.pusher = DBPusher(self.db)
        self.scheduler = BlockingScheduler()
        self.sched_cfg = self.db.config.get("scheduler", {})
        self.target_tables = self.db.config.get("target_tables", ["data_sample"])
        self.batch_size = self.sched_cfg.get("batch_size", 1)

    def run_job(self):
        """Executes one data generation and insertion cycle across target tables."""
        logger.info(f"--- Starting scheduled data generation cycle for target tables: {self.target_tables} ---")
        try:
            for table in self.target_tables:
                records = self.generator.generate_batch(table_name=table, count=self.batch_size)
                inserted = self.pusher.insert_records(table_name=table, records=records)
                logger.info(f"Cycle completed: Inserted {inserted} record(s) into {table}.")
        except Exception as e:
            logger.error(f"Error during scheduled job execution: {e}")

    def start(self):
        mode = self.sched_cfg.get("mode", "interval").lower()
        interval_seconds = self.sched_cfg.get("interval_seconds", 60)
        cron_expr = self.sched_cfg.get("cron_expression", "*/1 * * * *")

        if mode == "cron":
            logger.info(f"Configuring scheduler with Cron Expression: '{cron_expr}'")
            # Parse cron expression (5 fields: minute, hour, day, month, day_of_week)
            parts = cron_expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4]
                )
            else:
                logger.warning(f"Invalid cron expression '{cron_expr}'. Defaulting to interval trigger ({interval_seconds}s).")
                trigger = IntervalTrigger(seconds=interval_seconds)
        else:
            logger.info(f"Configuring scheduler with Interval Trigger: Every {interval_seconds} seconds.")
            trigger = IntervalTrigger(seconds=interval_seconds)

        self.scheduler.add_job(self.run_job, trigger, id="db_data_generator_job", replace_existing=True)

        def shutdown_handler(signum, frame):
            logger.info("Received termination signal. Shutting down scheduler gracefully...")
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self.db.close_all()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        logger.info("Starting Cron Scheduler Daemon. Press Ctrl+C to stop.")
        
        # Run an initial immediate cycle on startup
        self.run_job()

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
            self.db.close_all()

if __name__ == "__main__":
    daemon = CronSchedulerDaemon()
    daemon.start()
