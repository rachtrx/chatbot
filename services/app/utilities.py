import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
from extensions import get_session, remove_thread_session
import inspect
import traceback
from sqlalchemy import inspect as sql_inspect
import threading
import os
from dotenv import load_dotenv

env_path = f"/etc/environment"
load_dotenv(dotenv_path=env_path)

if os.environ.get('LIVE') == "1":
    log_level = logging.ERROR
else:
    log_level = logging.INFO

singapore_tz = ZoneInfo('Asia/Singapore')

def log_instances(session, func_name):
    logging.info(f'printing instances in {func_name}, session id = {id(session)}')
    for instance in session.identity_map.values():
        logging.info(instance)
    logging.info("end print")

def convert_utc_to_sg_tz(utc_timestamp, dt_type=None):

    singapore_time = utc_timestamp.astimezone(singapore_tz)

    if dt_type:
        return singapore_time.strftime(dt_type)
    else:
        return singapore_time
    

def current_sg_time(dt_type=None, day_offset = 0): # removed hour_offset

    dt = datetime.now(singapore_tz)

    # if hour_offset:
    #     dt = dt.replace(hour=hour_offset, minute=0, second=0, microsecond=0)

    if day_offset:
        dt = dt + timedelta(days=day_offset)

    if dt_type:
        return dt.strftime(dt_type)
    else:
        return dt
    
def get_latest_date_past_8am():

    timenow = current_sg_time()

    logging.info(f"TIMENOW: {timenow}")

    if timenow.hour >= 8:
        tomorrow = timenow + timedelta(days=1)
        return tomorrow.date()
    else:
        return timenow.date()

def join_with_commas_and(lst):
    if not lst:
        return ""
    if len(lst) == 1:
        return lst[0]
    return ", ".join(lst[:-1]) + " and " + lst[-1]

##########################################
# FINDING CONSECUTIVE DATES FUNCTION
##########################################

# def parse_date(date_str):
#     # Remove the leading apostrophe and parse the date
#     return datetime.strptime(date_str.lstrip("'"), "%d/%m/%Y")

def find_consecutive_date_groups(dates):
    
    groups = []
    current_group = [dates[0]]

    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]) == timedelta(days=1):
            current_group.append(dates[i])
        else:
            groups.append(current_group)
            current_group = [dates[i]]
    
    groups.append(current_group)
    return groups

def format_date_groups(groups):
    formatted_groups = []

    for group in groups:
        logging.info(f"group: {group}")
        if len(group) > 1:
            first_date = group[0].strftime("%d/%m/%Y")
            last_date = group[-1].strftime("%d/%m/%Y")
            formatted_groups.append(f"{first_date} to {last_date}")
        else:
            formatted_groups.append(group[0].strftime("%d/%m/%Y"))
        

    return join_with_commas_and(formatted_groups)

def print_all_dates(dates, date_obj=False):
    '''This function takes in a random array of date objects and returns it nicely as a string'''
    if date_obj:
        parsed_dates = sorted(date for date in dates)
    else:
        parsed_dates = sorted(datetime.strptime(date, "%d/%m/%Y").date() for date in dates)
    logging.info(f"Parsed dates: {parsed_dates}")
    date_groups = find_consecutive_date_groups(parsed_dates)
    formatted_string = format_date_groups(date_groups)
    logging.info(f"formatted string: {formatted_string}")
    return formatted_string

def check_obj_state(obj):
    inspector = sql_inspect(obj)

    if inspector.transient:
        logging.info("Object is transient (not attached to any session, not saved to the database)")
    elif inspector.pending:
        logging.info("Object is pending (attached to a session but not yet saved to the database)")
    elif inspector.persistent:
        logging.info("Object is persistent (attached to a session, saved to the database)")
    elif inspector.detached:
        logging.info("Object is detached (was attached to a session, but now is not)")