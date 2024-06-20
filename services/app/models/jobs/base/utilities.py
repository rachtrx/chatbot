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

from extensions import get_session, remove_thread_session, redis_client

singapore_tz = ZoneInfo('Asia/Singapore')

def set_user_state(user_id, state, timeout=30):
    """Set the user as active with a specified timeout."""
    redis_client.setex(f"user:{user_id}:status", timeout, state.value)

def check_user_state(user_id, state):
    """Check if the user is currently marked as active."""
    return redis_client.exists(f"user:{user_id}:status") == state.value

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
    
def get_latest_date_past_hour(hour=9):

    timenow = current_sg_time()

    logging.info(f"TIMENOW: {timenow}")

    if timenow.hour >= hour:
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

def run_new_context(func):
    '''used on instance methods that are ran in a new thread'''
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        from manage import create_app

        result = None

        if kwargs.get('wait_time'):
            wait_time = kwargs.pop('wait_time')
            time.sleep(wait_time)

        app = create_app()
        with app.app_context():
            session = get_session()
            logging.info("In decorator")

            try:                           
                logging.info(id(session))
                result = func(self, *args, **kwargs)
                logging.info(f"Result in decorator: {result}")

            except Exception as e:
                session.rollback()
                logging.error("Something went wrong! Exception in decorator")
                logging.error(traceback.format_exc())
                raise
            finally:
                logging.info(id(session))
                if threading.current_thread() == threading.main_thread():
                    logging.info("This is running in the main thread.")
                else:
                    logging.info("This is running in a separate thread.")
                    remove_thread_session()
                return result
    return wrapper


# from contextlib import contextmanager
# from sqlalchemy.exc import OperationalError, DBAPIError

# class User(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     username = db.Column(db.String(80), unique=True, nullable=False)

# @contextmanager
# def session_scope():
#     """Provide a transactional scope around a series of operations."""
#     session = db.session()
#     try:
#         yield session
#         session.commit()
#     except:
#         session.rollback()
#         raise
#     finally:
#         session.close()

# def retry_operation(session, func, max_attempts=5, initial_wait=0.1, backoff_factor=2):
#     """Attempt a DB operation with retries on failure.

#     Args:
#         session (SQLAlchemy.Session): The database session.
#         func (callable): A function to execute that performs the operation.
#         max_attempts (int): Maximum number of retry attempts.
#         initial_wait (float): Initial wait time between retries in seconds.
#         backoff_factor (int): Factor by which to increase wait time after each retry.
#     """
#     attempt = 0
#     wait_time = initial_wait
#     while attempt < max_attempts:
#         try:
#             result = func(session)
#             session.commit()
#             return result  # Return or break after successful execution and commit
#         except (OperationalError, DBAPIError) as e:
#             session.rollback()  # Roll back the transaction before retrying
#             attempt += 1
#             if attempt == max_attempts:
#                 print(f"Failed after {max_attempts} attempts.")
#                 break  # Optionally, you can return or raise a custom exception here
#             time.sleep(wait_time)
#             wait_time *= backoff_factor
#             print(f"Retrying operation, attempt {attempt}...")
#         except Exception as e:
#             print(f"An unexpected error occurred: {e}")
#             session.rollback()
#             break

# def update_user(session, user_id, new_username):
#     user = session.query(User).filter(User.id == user_id).with_for_update().one()
#     user.username = new_username

# @app.route('/update_user/<int:user_id>/<new_username>')
# def web_update_user(user_id, new_username):
#     with session_scope() as session:
#         retry_operation(session, lambda s: update_user(s, user_id, new_username))
#         return "Update attempted."