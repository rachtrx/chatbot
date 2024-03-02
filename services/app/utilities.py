import time
from datetime import datetime, timedelta
import pytz
import logging
from functools import wraps
from extensions import db
from models.exceptions import ReplyError
import inspect
import traceback
from sqlalchemy.orm import scoped_session, sessionmaker
import threading

from flask import has_request_context, current_app

ThreadSession = None

def init_thread_session(engine):
    global ThreadSession
    ThreadSession = scoped_session(sessionmaker(bind=engine))

def get_session():
    if has_request_context():
        return current_app.extensions['sqlalchemy'].db.session
    else:
        return ThreadSession()

def run_new_context(wait_time=None):
    def decorator(func):
        @wraps(func)
        def wrapper(self_or_cls, *args, **kwargs):
            from manage import create_app
            from models.jobs.abstract import Job
            from models.messages.abstract import Message

            logging.basicConfig(
                filename='/var/log/app.log',  # Log file path
                filemode='a',  # Append mode
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
                level=logging.INFO  # Log level
            )

            if wait_time:
                time.sleep(wait_time)

            app = create_app()
            with app.app_context():
                session = get_session()

                logging.info("In decorator")

                try:
                    session.merge(self_or_cls)
                    if inspect.isclass(self_or_cls):
                        func(self_or_cls, *args, **kwargs)
                    else:
                        # Instance method logic
                        pri_key = getattr(self_or_cls, 'job_no', getattr(self_or_cls, 'sid', None))
                        dynamic_attrs = {attr: getattr(self_or_cls, attr) for attr in dir(self_or_cls) \
                                        if not attr.startswith('__') and not callable(getattr(self_or_cls, attr)) \
                                        and not hasattr(self_or_cls.__class__, attr)}
                        db_instance = session.query(type(self_or_cls)).get(pri_key)
                        logging.info(f"db instance found: {db_instance}")

                        if db_instance:
                            if isinstance(self_or_cls, Job) and self_or_cls.locked:
                                for _ in range(300):
                                    time.sleep(5)
                                    session.refresh(self_or_cls)
                                    if not self_or_cls.locked:
                                        break
                                if not self_or_cls.locked:
                                    self_or_cls.lock(session)
                                    session.commit()
                                else:
                                    raise Exception
                            for attr, value in dynamic_attrs.items():
                                setattr(db_instance, attr, value)
                            self_or_cls = db_instance

                        logging.info(id(session))
                        func(self_or_cls, *args, **kwargs)
                        if isinstance(self_or_cls, Job):
                            self_or_cls.unlock(session)

                except Exception as e:
                    session.rollback()
                    logging.error("Something went wrong! Exception in decorator")
                    logging.error(traceback.format_exc())
                finally:
                    logging.info(id(session))
                    if threading.current_thread() == threading.main_thread():
                        logging.error("This is running in the main thread.")
                    else:
                        logging.error("This is running in a separate thread.")
                        ThreadSession.remove()
        return wrapper
    return decorator


def current_sg_time(dt_type=None, hour_offset = None):
    singapore_tz = pytz.timezone('Asia/Singapore')

    dt = datetime.now(singapore_tz)

    if hour_offset:
        dt = dt.replace(hour=hour_offset, minute=0, second=0, microsecond=0)

    if dt_type:
        return dt.strftime(dt_type)
    else:
        return dt
    
def get_latest_date_past_8am():

    timenow = current_sg_time(hour_offset=8)

    if timenow.hour >= 8:
        tomorrow = timenow + timedelta(days=1)
        return tomorrow.date()
    else:
        return timenow.date()



def loop_relations(func):
    '''This wrapper wraps any function that takes in a user and loops over their relations.
    
    Returns a list of each relation function call result if there are relations, returns None if no relations.
    
    The function being decorated has a must have relation as the first param such that it can use the relation, but when calling it, it will take in the user'''
    
    def wrapper(user, *args, **kwargs):

        relations = user.get_relations()

        if all(relation is None for relation in relations):
            return None
        
        result = []

        for relation in relations:
            if relation is None:
                continue

            result.append(func(relation, *args, **kwargs))
        return result
    return wrapper

def join_with_commas_and(lst):
    if not lst:
        return ""
    if len(lst) == 1:
        return lst[0]
    return ", ".join(lst[:-1]) + " and " + lst[-1]

@loop_relations
def get_relations_name_and_no_list(relation):
    '''With the decorator, it returns a list as [(relation_name, relation_number), (relation_name, relation_number)]'''
    
    # return [relation.name, str(relation.number)]
    return (relation.name, str(relation.number))

def print_relations_list(relations_list):
    '''this function is commonly used after get_relations_name_and_no_list to loop through the relations'''
    user_list = []
    for name, number in relations_list:
        user_list.append(f"{name} ({number})")

    return join_with_commas_and(user_list)








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
