from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo
from config import settings
from db import Db
from msg_idiom import get_random_idiom, gen_msg
from tg import send_tg_msg_to_all


def send_daily_idiom():
    idiom_eng_text, randint_str = get_random_idiom()
    idiom_result_text = gen_msg(idiom_eng_text)
    Db.add_idiom(int(randint_str), idiom_result_text)
    if not idiom_result_text:
        return False
    tg_ids = Db.get_users_tg_ids()
    status_send = send_tg_msg_to_all(idiom_result_text, tg_ids)
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
