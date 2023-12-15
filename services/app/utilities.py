import time
from datetime import datetime
import pytz
from models.exceptions import AzureSyncError

def join_with_commas_and(lst):
    if not lst:
        return ""
    if len(lst) == 1:
        return lst[0]
    return ", ".join(lst[:-1]) + " and " + lst[-1]


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


def delay_decorator(message, seconds = 1, retries = 5):
    def outer_wrapper(func):
        def inner_wrapper(*args, **kwargs):
            count = 0
            while (count < retries):
                response = func(*args, **kwargs)
                if 200 <= response.status_code < 300:
                    return response
                else:
                    time.sleep(seconds)
                count += 1
            raise AzureSyncError(f"{message}. {response.json()}")

            
        return inner_wrapper
    return outer_wrapper

def current_sg_time():
    current_time_singapore = datetime.now(pytz.timezone('Asia/Singapore'))
    return current_time_singapore