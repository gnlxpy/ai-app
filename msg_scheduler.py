from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo
from config import settings
from db import Db
from msg_idiom import gen_msg_idiom
from tg import send_tg_msg_to_all


def send_daily_idiom() -> bool:
    idiom_dict = Db.get_random_idiom()
    if not idiom_dict:
        return False
    idiom_result_text = gen_msg_idiom(idiom_dict)
    if not idiom_result_text:
        return False
    Db.insert_idioms_history(idiom_dict['idiom'], idiom_result_text)
    tg_ids = Db.get_users_tg_ids()
    if not tg_ids:
        return False
    status_send = send_tg_msg_to_all(idiom_result_text, tg_ids)
    status_send = True
    return status_send


def start_scheduler():
    scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Tbilisi"))
    scheduler.add_job(
        send_daily_idiom,
        "cron",
        hour=int(settings.IDIOMS_SCHEDULE_TIME),
        minute=0,
        id="daily_idiom",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    return scheduler
