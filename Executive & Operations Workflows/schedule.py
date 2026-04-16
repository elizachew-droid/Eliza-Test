"""
Scheduler — runs morning_pulse every day at 8:45 AM (America/New_York).
Start with: python schedule.py
Or deploy as a cron job / systemd service using cron_entry.txt.
"""

import datetime
import time
import logging
from zoneinfo import ZoneInfo

import schedule

from morning_pulse import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
TZ = ZoneInfo("America/New_York")


def _job():
    logging.info("Running morning pulse...")
    try:
        run()
    except Exception as exc:
        logging.exception("Morning pulse failed: %s", exc)


schedule.every().day.at("08:45").do(_job)

logging.info("Scheduler started — morning pulse will fire at 08:45 ET daily.")

while True:
    schedule.run_pending()
    time.sleep(30)
