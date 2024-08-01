import time
import inspect
import os
import logging
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import threading
from functools import wraps
from sqlalchemy import inspect as sql_inspect

from extensions import Session, redis_client

# print(f"Active thread count: {active_thread_count}")

singapore_tz = ZoneInfo('Asia/Singapore')

def set_user_state(user_id, state, timeout=30):
    """Set the user as active with a specified timeout."""
    redis_client.setex(f"user:{user_id}:status", timeout, state)

def check_user_state(user_id, state):
    """Check if the user is currently marked as active."""
    return redis_client.exists(f"user:{user_id}:status") == state

def is_user_status_exists(user_id):
    """Check if the user's status has been deleted."""
    return redis_client.exists(f"user:{user_id}:status") != 0

def clear_user_processing_state(user_id):
    """Clear the active mark for the user."""
    redis_client.delete(f"user:{user_id}:status")

def combine_with_key_increment(original_dict, new_dict):
    # Convert all keys to integers for processing
    temp_original = {int(k): v for k, v in original_dict.items()}
    temp_new = {int(k): v for k, v in new_dict.items()}
    
    for new_key, new_value in temp_new.items():
        # If the key exists in the original dictionary, resolve conflicts
        while new_key in temp_original:
            # Shift the existing value to the next key
            temp_original = {k + 1 if k >= new_key else k: v for k, v in temp_original.items()}
        # Insert the new item
        temp_original[new_key] = new_value
    
    # convert numbers to strings
    return {str(k): v for k, v in temp_original.items()}

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
    

def current_sg_time(day_offset = 0): # removed hour_offset

    dt = datetime.now(singapore_tz)
    if day_offset:
        dt = dt + timedelta(days=day_offset)
    return dt
    
def get_latest_date_past_hour(hour=9, day_offset=0):

    present_day = current_sg_time(day_offset)

    logging.info(f"present_day: {present_day}")

    if present_day.hour >= hour:
        next_day = present_day + timedelta(days=1)
        return next_day.date()
    else:
        return present_day.date()

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

def print_all_dates(dates, date_obj=True):
    logging.info(f"Dates: {dates}")
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

def run_new_context(func):
    '''used on instance methods that are ran in a new thread'''
    @wraps(func)
    def wrapper(*args, **kwargs):
        from manage import create_app

        result = None

        if kwargs.get('wait_time'):
            wait_time = kwargs.pop('wait_time')
            logging.info(f"Waiting for {wait_time} seconds...")
            time.sleep(wait_time)

        logging.info("Starting function in decorator")

        with create_app().app_context():
            session = Session()
            logging.info(f" Opening session in new context: {id(session)}")

            try:                           
                instance_or_class = args[0]
                if isinstance(instance_or_class, type):
                    result = func(*args, **kwargs)
                else:
                    result = func(instance_or_class, *args[1:], **kwargs)
                logging.info(f"Result in decorator: {result}")

            except Exception as e:
                session.rollback() # TODO
                logging.error("Exception caught in decorator")
                logging.error(traceback.format_exc())
                raise
            finally:
                logging.info(f" Closing session in new context: {id(session)}")
                session.close()
                return result
    return wrapper
