import re
import logging
from datetime import datetime, timedelta, date

from models.users import User

from models.jobs.base.utilities import print_all_dates, current_sg_time, get_latest_date_past_hour, join_with_commas_and

from models.jobs.leave.constants import LeaveIssue, Patterns
from models.jobs.leave.LeaveRecord import LeaveRecord

def set_dates_str(dates, mark_late):
    dates_str = print_all_dates(dates, date_obj=True)

    if mark_late:
        cur_date = current_sg_time().date()
        cur_date_str = cur_date.strftime('%d/%m/%Y')

        if get_latest_date_past_hour() > cur_date:
            dates_str = re.sub(cur_date_str, cur_date_str + ' (*LATE*)', dates_str)

    return dates_str
    
def print_overlap_dates(dates):
    return LeaveIssue.OVERLAP.value + print_all_dates(dates, date_obj=True)

def print_updated_dates(dates_to_approve):
    return LeaveIssue.LATE.value + print_all_dates(dates_to_approve, date_obj=True)

@User.loop_users # just need to pass in the user when calling get_approve_leave_cv
def get_approve_leave_cv(relation, alias, leave_type, dates, mark_late=False, approver_alias=None):
    '''LEAVE_NOTIFY_APPROVE_SID and LEAVE_NOTIFY_CANCEL_SID; The decorator is for SENDING MESSAGES TO ALL RELATIONS OF ONE PERSON'''
    
    duration = len(dates)

    return {
        '1': relation.alias,
        '2': alias,
        '3': leave_type.lower(),
        '4': f"{str(duration)} {'day' if duration == 1 else 'days'}",
        '5': set_dates_str(dates, mark_late),
        '6': approver_alias if approver_alias else 'None'
    }

@User.loop_users # just need to pass in the user when calling get_approve_leave_cv
def get_cancel_leave_cv(relation, alias, is_approved, dates):
    return {
        '1': relation.alias,
        '2': alias,
        '3': 'leave' if is_approved else 'leave request',
        '4': set_dates_str(dates)
    }

@User.loop_users # just need to pass in the user when calling get_approve_leave_cv
def get_reject_leave_cv(relation, approver_alias, dates, alias):

    return {
        '1': relation.alias,
        '2': approver_alias,
        '3': set_dates_str(dates),
        '4': alias
    }

@User.loop_users
def get_authorisation_cv(relation, alias, leave_type, dates, relation_aliases, mark_late=False):
    local_relation_aliases = relation_aliases.copy()
    local_relation_aliases.discard(relation.alias)

    duration = len(dates)

    return {
        '1': relation.alias,
        '2': alias,
        '3': leave_type.lower(),
        '4': f"{duration} {'day' if duration == 1 else 'days'}",
        '5': set_dates_str(dates, mark_late),
        '6': join_with_commas_and(list(local_relation_aliases))
    }


@User.loop_users
def get_authorisation_late_cv(relation, alias, leave_type, dates_approved, dates_to_authorise, relation_aliases, mark_late=False):
    local_relation_aliases = relation_aliases.copy()
    local_relation_aliases.discard(relation.alias)

    duration_approved = len(dates_approved)
    duration_to_authorise = len(dates_to_authorise)
    
    return {
        '1': relation.alias,
        '2': alias,
        '3': leave_type.lower(mark_late),
        '4': f"{duration_approved} {'day' if duration_approved == 1 else 'days'}",
        '5': set_dates_str(dates_approved, mark_late),
        '6': f"{str(duration_to_authorise)} {'day' if duration_to_authorise == 1 else 'days'}",
        '7': set_dates_str(dates_to_authorise, mark_late),
        '8': join_with_commas_and(list(local_relation_aliases))
    }

##################
# SECTION REGEX
##################

def generate_date_obj(match_obj, date_format):
    '''returns date object from the regex groups, where there are typically 2 groups: start date and end date'''
    logging.info("matching dates")
    date = None
    logging.info(match_obj.group("date"), match_obj.group("month"))
    if match_obj.group("date") and match_obj.group("month"):
        date = f'{match_obj.group("date")} {match_obj.group("month")} {current_sg_time().year}'
        date = datetime.strptime(date, date_format).date() # create datetime object

    return date

# SECTION 1. eg. 5 December OR December 5

def replace_with_full_month(match):
    '''pass in the match object from the sub callback and return the extended month string'''
    # Get the matched abbreviation or full month name
    month_key = match.group(0).lower()
    # Return the capitalized full month name from the dictionary
    return Patterns.MONTH_MAPPING[month_key]

def named_month_extraction(message):
    '''Check for month pattern ie. 11 November or November 11'''
    user_str = re.sub(Patterns.MONTHS_LOOSE, replace_with_full_month, message, flags=re.IGNORECASE)
    
    def get_dates(start_date_pattern, end_date_pattern):
        start_match_dates = start_date_pattern.search(user_str)
        end_match_dates = end_date_pattern.search(user_str)
        start_date = end_date = None
        if start_match_dates: 
            start_date = generate_date_obj(start_match_dates, "%d %B %Y")
        if end_match_dates:
            end_date = generate_date_obj(end_match_dates, "%d %B %Y")
            if start_date == None:
                start_date = current_sg_time().date()
        return (start_date, end_date)

    dates = get_dates(Patterns.START_DATE_PATTERN, Patterns.END_DATE_PATTERN) # try first pattern
    
    if len([date for date in dates if date is not None]) > 0:
        return dates
    else:
        dates = get_dates(Patterns.START_DATE_PATTERN_2, Patterns.END_DATE_PATTERN_2) # try 2nd pattern
        return dates
    

# SECTION 2. 5/12 

def named_ddmm_extraction(leave_message):
    '''Check for normal date pattern ie. 11/11 or something'''

    match_start_dates = Patterns.DDMM_START_DATE.search(leave_message)
    match_end_dates = Patterns.DDMM_END_DATE.search(leave_message)

    start_date = end_date = None

    # try:
    if match_start_dates:
        start_date = generate_date_obj(match_start_dates, "%d %m %Y")
    if match_end_dates:
        end_date = generate_date_obj(match_end_dates, "%d %m %Y")
        if start_date == None:
            start_date = current_sg_time().date()

    return (start_date, end_date)


# SECTION 3. 5 days leave OR leave for 5 days
def duration_extraction(message):
    '''ran always to check if user gave any duration'''

    match_duration = Patterns.DURATION_PATTERN.search(message)
    if match_duration:
        duration = match_duration.group("duration1") or match_duration.group("duration2")
        logging.info(f'DURATION: {duration}')
        return duration

    return None

def calc_start_end_date(duration):
    '''ran when start_date and end_date is False; takes in extracted duration and returns the calculated start and end date. need to -1 since today is the 1st day. This function is only used if there are no dates. It does not check if dates are correct as the duration will be assumed to be wrong'''
    logging.info("manually calc days")
    logging.info(duration)
    start_date = current_sg_time().date()
    end_date = (start_date + timedelta(days=int(duration) - 1))

    return start_date, end_date


# SECTION 4. next tues
# ignore all the "this", it will be handled later. 
def resolve_day(day_key):
    today = date.today()
    today_weekday = today.weekday()

    if day_key in ['today', 'tdy']:
        return Patterns.DAYS_STRICT[today_weekday] # today
    else:
        return Patterns.DAYS_STRICT[(today_weekday + 1) % 7] # tomorrow

def replace_with_full_day(match):
    '''pass in the match object from the sub callback and return the extended month string'''
    # Get the matched abbreviation or full month name
    prefix = match.group('prefix') + (' ' + match.group('offset') if match.group('offset') is not None else '')
    day_key = match.group('days').lower()
    logging.info(prefix)

    if day_key in ['today', 'tomorrow', 'tmr', 'tdy']:
        return prefix + ' ' + resolve_day(day_key)

    # Return the capitalized full month name from the dictionary
    return prefix + ' ' + Patterns.DAY_MAPPING[day_key]

def named_day_extraction(message):
    '''checks the body for days, returns (start_date, end_date)'''

    logging.info(Patterns.START_DAY_PATTERN)
    logging.info(f"negative lookbehinds: {Patterns.NEGATIVE_LOOKBEHINDS}")

    # days_regex, start_day_pattern, and end_day_pattern can be found in constants.py
    user_str = re.sub(Patterns.DAYS_OF_WEEK_PATTERN, replace_with_full_day, message, flags=re.IGNORECASE)

    start_days = Patterns.START_DAY_PATTERN.search(user_str)
    end_days = Patterns.END_DAY_PATTERN.search(user_str)

    start_week_offset = 0
    end_week_offset = 0

    start_day = end_day = None

    if start_days:
        logging.info("start days found")
        start_week_offset = 0
        start_buffer = start_days.group("start_buffer") # retuns "next" or None
        start_day = start_days.group("start_day")
        logging.info(f'start day: {start_day}')
        if start_buffer != None:
            start_week_offset = 1

    if end_days:
        logging.info("end days found")
        end_week_offset = 0
        end_buffer = end_days.group("end_buffer") # retuns "next" or None
        end_day = end_days.group("end_day")
        logging.info(f'end day: {end_day}')
        if end_buffer != None:
            end_week_offset = 1
            end_week_offset -= start_week_offset

    if start_day == None and end_day == None:
        return (None, None)

    return get_future_date(start_day, end_day, start_week_offset, end_week_offset) # returns (start_date, end_date)

def get_future_date(start_day, end_day, start_week_offset, end_week_offset):
    today = date.today()
    today_weekday = today.weekday()

    if start_day != None:
        start_day = Patterns.DAYS_STRICT.index(start_day)

        # if past the start day, then next will mean adding the remaining days of the week and the start day
        if today_weekday > start_day:
            diff = 7 - today_weekday + start_day
            if start_week_offset > 0:
                start_week_offset -= 1
            # if end_week_offset > 0:
            #     end_week_offset -= 1 #TODO TEST
        else:
            logging.info(start_week_offset, end_week_offset)
            diff = start_day - today_weekday
        start_date = today + timedelta(days=diff + 7 * start_week_offset)
        
    else:
        start_day = today_weekday # idea of user can give the until day without start day and duration
        start_date = today
        
    if end_day != None:
        end_day = Patterns.DAYS_STRICT.index(end_day)
        if start_day > end_day:
            # if end day comes before start day, then add the remaining days of the week and the end day
            diff = 7 - start_day + end_day
            if end_week_offset > 0:
                end_week_offset -= 1
        else:
            diff = end_day - start_day
        logging.info(end_week_offset)
        end_date = start_date + timedelta(days=diff + 7 * end_week_offset)
    else:
        end_date = None

    logging.info(start_date, end_date)

    return (start_date, end_date)
