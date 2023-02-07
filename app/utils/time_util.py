from datetime import datetime, timedelta, timezone
from time import time
from types import MappingProxyType
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from app import config


def current_time():
    return datetime.now(ZoneInfo(config.TZ))


def get_time_range_from_now(range: str | int | datetime):
    match range:
        case str():
            return current_time() - relativedelta(days=date_range_mapper[range.upper()])
        case int():
            return current_time() - relativedelta(days=range)
        case datetime():
            return current_time() - range


def timestamp_in_miliseconds():
    return round(time() * 1000)


date_range_mapper = MappingProxyType(
    {
        "TODAY": 1,
        "A_WEEK": 7,
        "A_MONTH": 30,
        "THREE_MONTH": 90,
        "SIX_MONTH": 180,
        "YEAR": 365,
    }
)


def locate_start_and_end_dates_on_frequency(
    settlement_frequency: int,
    confirm_date: datetime | None = None,
    country: str = "KR",
    settlement_desired_date: int | None = None,
) -> tuple[datetime, datetime]:  # type: ignore
    """
    Given the frequency, and current datetime, need to produce settlement duration
    """
    confirm_date = current_time() if confirm_date is None else confirm_date

    curr_timezone = timezone.utc
    if country == "KR":
        curr_timezone = timezone(timedelta(hours=9))

    confirm_date_with_timezone = confirm_date.astimezone(curr_timezone)

    # half of month
    if settlement_frequency == 2:
        fst_date = confirm_date_with_timezone.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sec_date = confirm_date_with_timezone.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
        thd_date = (confirm_date_with_timezone + relativedelta(months=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if fst_date <= confirm_date_with_timezone < sec_date:
            return fst_date.astimezone(timezone.utc), minus_one_ms(sec_date).astimezone(timezone.utc)
        if sec_date <= confirm_date_with_timezone < thd_date:
            return sec_date.astimezone(timezone.utc), minus_one_ms(thd_date).astimezone(timezone.utc)

    # every month(settlement_frequency == 1)
    end_date = confirm_date_with_timezone + relativedelta(months=1)
    end_date = minus_one_ms(end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0))

    return (
        confirm_date_with_timezone.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc),
        end_date.astimezone(timezone.utc),
    )


def minus_one_ms(date_time: datetime):
    return date_time - relativedelta(microseconds=1)


def gen_date_range_str_kst(start_date: datetime, end_date: datetime):
    kst = timezone(timedelta(hours=9))
    start_date_kst = start_date.astimezone(tz=kst)
    end_date_kst = end_date.astimezone(tz=kst)

    return f"{start_date_kst.strftime('%Y.%m.%d')} ~ {end_date_kst.strftime('%Y.%m.%d')}"


def gen_date_str_kst(date: datetime | None = None):
    kst = timezone(timedelta(hours=9))
    if not date:
        return "-"
    kst_date = date.astimezone(tz=kst)
    return kst_date.strftime("%Y.%m.%d")
