from datetime import datetime, timedelta, date
from constants import month_mapping, days_arr, day_mapping, leave_alt_words
import re
from dateutil.relativedelta import relativedelta
import logging
import traceback
from utilities import current_sg_time

from MessageLoggersetup_logger

# SECTION utils
start_prefixes = r'from|on|for|starting|doctor|leave|mc|appointment|sick|doctor|ml|ccl|npl|medical cert|medical certificate'
# added these incase users say I am on mc today
end_prefixes = r'to|until|til|till|ending'

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
months_regex = r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b' # required to alter user string

months = r'January|February|March|April|May|June|July|August|September|October|November|December'

date_pattern = r'(?P<date>\d{1,2})(st|nd|rd|th)?'
month_pattern = r'(?P<month>' + months + r')'

date_first_pattern = date_pattern + r'\s*' + month_pattern
month_first_pattern = month_pattern + r'\s*' + date_pattern

start_date_pattern = r'(' + start_prefixes + ')\s(' + date_first_pattern + r')'
end_date_pattern = r'(' + end_prefixes + ')\s(' + date_first_pattern + r')'

start_date_pattern_2 = r'(' + start_prefixes + ')\s(' + month_first_pattern + r')'
end_date_pattern_2 = r'(' + end_prefixes + ')\s(' + month_first_pattern + r')'

def replace_with_full_month(match):
    '''pass in the match object from the sub callback and return the extended month string'''
    # Get the matched abbreviation or full month name
    month_key = match.group(0).lower()
    # Return the capitalized full month name from the dictionary
    return month_mapping[month_key]

def named_month_extraction(message):
    '''Check for month pattern ie. 11 November or November 11'''
    user_str = re.sub(months_regex, replace_with_full_month, message, flags=re.IGNORECASE)

    #SECTION proper dates
    months = r'January|February|March|April|May|June|July|August|September|October|November|December'
    date_pattern = r'(?P<date>\d{1,2})(st|nd|rd|th)?'
    month_pattern = r'(?P<month>' + months + r')'

    date_first_pattern = date_pattern + r'\s*' + month_pattern
    month_first_pattern = month_pattern + r'\s*' + date_pattern

    start_date_pattern = r'(from|on)\s(' + date_first_pattern + r')'
    end_date_pattern = r'(to|until|til(l)?)\s(' + date_first_pattern + r')'

    start_date_pattern_2 = r'(from|on)\s(' + month_first_pattern + r')'
    end_date_pattern_2 = r'(to|until|til(l)?)\s(' + month_first_pattern + r')'
    

    def get_dates(start_date_pattern, end_date_pattern):
        compiled_start_date_pattern = re.compile(start_date_pattern, re.IGNORECASE)
        compiled_end_date_pattern = re.compile(end_date_pattern, re.IGNORECASE)
        start_match_dates = compiled_start_date_pattern.search(user_str)
        end_match_dates = compiled_end_date_pattern.search(user_str)
        start_date = end_date = None
        if start_match_dates: 
            start_date = generate_date_obj(start_match_dates, "%d %B %Y")
        if end_match_dates:
            end_date = generate_date_obj(end_match_dates, "%d %B %Y")
            if start_date == None:
                start_date = current_sg_time().date()
        return (start_date, end_date)

    dates = get_dates(start_date_pattern, end_date_pattern) # try first pattern
    
    if len([date for date in dates if date is not None]) > 0:
        return dates
    else:
        dates = get_dates(start_date_pattern_2, end_date_pattern_2) # try 2nd pattern
        return dates
    

# SECTION 2. 5/12 

dd_pattern = r'[12][0-9]|3[01]|0?[1-9]'
mm_pattern = r'1[0-2]|0?[1-9]'

ddmm_pattern = r'(?P<date>' + dd_pattern + r')/(?P<month>' + mm_pattern + r')'

ddmm_start_date_pattern = r'(' + start_prefixes + r')\s(' + ddmm_pattern + r')' 
ddmm_end_date_pattern = r'(' + end_prefixes + r')\s(' + ddmm_pattern + r')'

def named_ddmm_extraction(leave_message):
    '''Check for normal date pattern ie. 11/11 or something'''

    compiled_start_date_pattern = re.compile(ddmm_start_date_pattern, re.IGNORECASE)
    compiled_end_date_pattern = re.compile(ddmm_end_date_pattern, re.IGNORECASE)

    match_start_dates = compiled_start_date_pattern.search(leave_message)
    match_end_dates = compiled_end_date_pattern.search(leave_message)

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
duration_pattern = r'(?P<duration1>\d\d?\d?|a)'
alternative_duration_pattern = r'(?P<duration2>\d\d?\d?|a)' # need to have both so that can be compiled together (otherwise it will be rejected in that OR)
day_pattern = r'(day|days)'

leave_type_max_two_words = r'(\b\w+\b\s+){0,2}'

# Combine the basic patterns into two main alternatives. use the loose keywords for this, in case its a retry. if first try, allow max 2 words before "leave"
alternative1 = duration_pattern + r'\s.*?' + day_pattern + r'\s.*?' + leave_type_max_two_words + leave_alt_words
alternative2 = leave_type_max_two_words + leave_alt_words + r'\s.*?' + alternative_duration_pattern + r'\s.*?' + day_pattern

# Combine the two main alternatives into the final pattern
final_duration_extraction = r'\b.*?(?:on|taking|take) (' + alternative1 + r'|' + alternative2 + r')\b'

def duration_extraction(message):
    '''ran always to check if user gave any duration'''

    # Combine the two main alternatives into the final pattern
    urgent_absent_pattern = re.compile(final_duration_extraction, re.IGNORECASE)

    match_duration = urgent_absent_pattern.search(message)
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
days_regex = r'\b(?P<prefix>' + start_prefixes + r'|' + end_prefixes + r')\s*(this)?\s*(?P<offset>next|nx)?\s(?P<days>mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|today|tomorrow|tmr|tdy)\b' # required to alter user string

# done fixing the day names
days_pattern = r'Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday'
end_prefixes_list = end_prefixes.split('|')
negative_lookbehinds = r"(?<!" + r"\s)(?<!".join(end_prefixes_list) + r"\s)"

start_day_pattern = rf'\s(?:{start_prefixes}|{negative_lookbehinds}(?P<start_buffer>next|nx))*\s(?P<start_day>{days_pattern})'

end_day_pattern = r'(?:' + end_prefixes + r')\s*(?P<end_buffer>next|nx)?\s(?P<end_day>' + days_pattern + r')'

def resolve_day(day_key):
    today = date.today()
    today_weekday = today.weekday()

    if day_key in ['today', 'tdy']:
        return days_arr[today_weekday] # today
    else:
        return days_arr[(today_weekday + 1) % 7] # tomorrow

def replace_with_full_day(match):
    '''pass in the match object from the sub callback and return the extended month string'''
    # Get the matched abbreviation or full month name
    prefix = match.group('prefix') + (' ' + match.group('offset') if match.group('offset') is not None else '')
    day_key = match.group('days').lower()
    logging.info(prefix)

    if day_key in ['today', 'tomorrow', 'tmr', 'tdy']:
        return prefix + ' ' + resolve_day(day_key)

    # Return the capitalized full month name from the dictionary
    return prefix + ' ' + day_mapping[day_key]

def named_day_extraction(message):
    '''checks the body for days, returns (start_date, end_date)'''

    logging.info(start_day_pattern)
    logging.info(f"negative lookbehinds: {negative_lookbehinds}")

    # days_regex, start_day_pattern, and end_day_pattern can be found in constants.py
    user_str = re.sub(days_regex, replace_with_full_day, message, flags=re.IGNORECASE)

    logging.info(f"new user string: {user_str}")

    compiled_start_day_pattern = re.compile(start_day_pattern, re.IGNORECASE)
    compiled_end_day_pattern = re.compile(end_day_pattern, re.IGNORECASE)

    start_days = compiled_start_day_pattern.search(user_str)
    end_days = compiled_end_day_pattern.search(user_str)

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
        start_day = days_arr.index(start_day)

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
        end_day = days_arr.index(end_day)
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

