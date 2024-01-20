import time
from datetime import datetime, timedelta
import pytz
import logging

def current_sg_time(dt_type=None, hour_offset = None):
    singapore_tz = pytz.timezone('Asia/Singapore')

    dt = datetime.now(singapore_tz)

    if hour_offset:
        dt = dt.replace(hour=hour_offset, minute=0, second=0, microsecond=0)

    if dt_type:
        return dt.strftime(dt_type)
    else:
        return dt


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
