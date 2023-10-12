import re
from datetime import datetime, timedelta
import spacy
from word2number import w2n

import os
from twilio.rest import Client

# account_sid = os.environ['TWILIO_ACCOUNT_SID']
# auth_token = os.environ['TWILIO_AUTH_TOKEN']
# client = Client(account_sid, auth_token)

import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

def extract_start_end_date(match_obj):
    start_date = f'{match_obj.group("start_date")} {match_obj.group("start_month")} {datetime.now().year}'
    end_date = f'{match_obj.group("end_date")} {match_obj.group("end_month")} {datetime.now().year}'

    print(f'start date: {start_date}, end date: {end_date}')
    return (start_date, end_date)

#SECTION Check for normal date pattern ie. 11/11 or somethijng
def named_ddmm_extraction(user_str):
    date_pattern = r'0?[1-9]|[12][0-9]|3[01]'
    month_pattern = r'0?[1-9]|1[0-2]'

    start_pattern = r'\b(?P<start_date>' + date_pattern + r')/(?P<start_month>' + month_pattern + r')\b'
    end_pattern = r'\b(?P<end_date>' + date_pattern + r')/(?P<end_month>' + month_pattern + r')\b'

    normal_date_pattern = r'\b' + start_pattern + r'\s' + r'(?P<join>to|until)'+ r'\s' + end_pattern + r'\b'

    compiled_normal_date_pattern = re.compile(normal_date_pattern, re.IGNORECASE)

    match_dates = compiled_normal_date_pattern.search(user_str)
    if match_dates:
        print('matched 3rd')
        return extract_start_end_date(match_dates)
    
    return False

# SECTION proper months
month_mapping = {
    'jan': 'January',
    'january': 'January',
    'feb': 'February',
    'february': 'February',
    'mar': 'March',
    'march': 'March',
    'apr': 'April',
    'april': 'April',
    'may': 'May',
    'jun': 'June',
    'june': 'June',
    'jul': 'July',
    'july': 'July',
    'aug': 'August',
    'august': 'August',
    'sep': 'September',
    'sept': 'September',
    'september': 'September',
    'oct': 'October',
    'october': 'October',
    'nov': 'November',
    'november': 'November',
    'dec': 'December',
    'december': 'December'
}

def replace_with_full_month(match):
    '''pass in the match object from the sub callback and return the extended month string'''
    # Get the matched abbreviation or full month name
    month_key = match.group(0).lower()
    # Return the capitalized full month name from the dictionary
    return month_mapping[month_key]

# start_pattern = r'(?P<prefix>.*)\b(?P<start_date>\d{1,2})(st|nd|rd|th)\b(?:\s+(?P<start_month>January|February|March|April|May|June|July|August|September|October|November|December))\s'
# end_pattern = r'\s+(?P<end_date>\d{1,2})(st|nd|rd|th)\b(?:\s*(?P<end_month>January|February|March|April|May|June|July|August|September|October|November|December))(?P<suffix>.*)'

def named_month_extraction(user_str):
    user_str = re.sub(r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b', replace_with_full_month, user_str, flags=re.IGNORECASE)

    #SECTION proper dates
    start_date_pattern = r'(?P<start_date>\d{1,2})(st|nd|rd|th)'
    start_month_pattern = r'(?P<start_month>January|February|March|April|May|June|July|August|September|October|November|December)'
    end_date_pattern = r'(?P<end_date>\d{1,2})(st|nd|rd|th)'
    end_month_pattern = r'(?P<end_month>January|February|March|April|May|June|July|August|September|October|November|December)'

    date_first_pattern = start_date_pattern + r'\s*' + start_month_pattern + r'\s' + r'(?P<join>to|until)' + r'\s' + end_date_pattern + r'\s*' + end_month_pattern
    month_first_pattern = start_month_pattern + r'\s*' + start_date_pattern + r'\s+' + r'(?P<join>to|until)' + r'\s+' + end_month_pattern + r'\s*' + end_date_pattern
    compiled_date_first_pattern = re.compile(date_first_pattern, re.IGNORECASE)
    compiled_month_first_pattern = re.compile(month_first_pattern, re.IGNORECASE)


    match_dates = compiled_date_first_pattern.search(user_str)
    # case 1 January to 2 January
    if match_dates:
        print('matched first')
        return extract_start_end_date(match_dates)
    else:
        # user_str = re.sub(date_first_pattern, r'\g<start_date> \g<start_month> \g<join> \g<end_date> \g<end_month>', user_str, flags=re.IGNORECASE)
        # print(user_str)
        # case January 1 to January 2
        match_dates = compiled_month_first_pattern.search(user_str)
        if match_dates:
            print('matched second')
            return extract_start_end_date(match_dates)
            # user_str = re.sub(date_first_pattern, r'\g<start_date> \g<start_month> \g<join> \g<end_date> \g<end_month>', user_str, flags=re.IGNORECASE)
    
    return False

def get_start_end_date(user_str):
    return named_month_extraction(user_str) or named_ddmm_extraction(user_str)



# SECTION Proper duration and general format
def duration_extraction(user_str):
    duration_pattern = r'(?P<duration1>\d\d?\d?|a)'
    alternative_duration_pattern = r'(?P<duration2>\d\d?\d?|a)'
    day_pattern = r'(day|days)'
    action_pattern = r'(leave|mc|appointment)'

    # Combine the basic patterns into two main alternatives
    alternative1 = r'.*?' + duration_pattern + r' ' + day_pattern + r' .*?' + action_pattern
    alternative2 = r'.*?' + action_pattern + r' .*?' + alternative_duration_pattern + r' ' + day_pattern

    # Combine the two main alternatives into the final pattern
    urgent_absent_pattern = re.compile(r'\b(?:on|taking|take) (' + alternative1 + r'|' + alternative2 + r')\b', re.IGNORECASE)

    match_duration = urgent_absent_pattern.search(user_str)
    if match_duration:
        duration = match_duration.group("duration1") or match_duration.group("duration2")
        print(f'duration: {duration}')
        return(duration)

    print(user_str)
    return False

def duration_calc(start_date, end_date, date_format = "%d %B %Y"):
    '''takes in a start date, end date, and the date format and returns the start and end date as strings, and the duration between the 2 datetime objects. 
    if duration is negative, it adds 1 to the year. also need to +1 to duration since today is included as well'''
    formatted_start_date = datetime.strptime(start_date, date_format)
    formatted_end_date = datetime.strptime(end_date, date_format)

    duration = (formatted_end_date - formatted_start_date).days + 1
    if duration < 0:
        formatted_end_date += relativedelta(years=1)
        duration = (formatted_end_date - formatted_start_date).days + 1

    return [formatted_start_date.strftime('%d/%m/%Y'), formatted_end_date.strftime('%d/%m/%Y'), duration]

def calc_start_end_date(duration):
    '''takes in extracted duration and returns the calculated start and end date. need to -1 since today is the 1st day'''
    start_date = datetime.now().date()
    end_date = (start_date + timedelta(days=int(duration) - 1))
    return (start_date.strftime('%d/%m/%Y'), end_date.strftime('%d/%m/%Y'))

# IMPT MOVED
def generate_mc_details(user_str):
    duration_e = duration_extraction(user_str)
    dates = get_start_end_date(user_str)
    if dates:
        start_date, end_date = dates
        try: # for named month format
            formatted_start_date, formatted_end_date, duration_c = duration_calc(start_date, end_date)
            print(formatted_start_date, formatted_end_date)
        except: # for digit month format
            try:
                formatted_start_date, formatted_end_date, duration_c = duration_calc(start_date, end_date, "%d %m %Y")
                print(formatted_start_date, formatted_end_date)
            except:
                return False 

        if duration_e != duration_c and duration_e:
            print("The durations do not match! Did you mean {duration_c} days?")
        return [formatted_start_date, formatted_end_date, duration_c]
    else:
        try:
            start_date, end_date = calc_start_end_date(duration_e)
            print(start_date, end_date)
            return [start_date, end_date, duration_e]
        except:
            return False

#IMPT MOVED
def check_for_intent(user_str):
    '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

    # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
    
    absent_keyword_patterns = re.compile(r'\b(?:leave|mc|sick|doctor)\b', re.IGNORECASE)
    match = absent_keyword_patterns.search(user_str)

    if match:
        return generate_mc_details(user_str)

def check_response(message):
    confirmation_pattern = re.compile(r'^(yes|no)$', re.IGNORECASE)
    
    if confirmation_pattern.match(message):
        return True
    return False

# SECTION sync with the excel file

def main():
    user_str = input("Hi what would you like to do? ")
    details = check_for_intent(user_str)
    if details:
        days, start_date, end_date = details
        print(f"Kindly confirm that you are on MC for {days} days from {start_date:%B %d} to {end_date:%B %d}")

    else:
        print("Sorry I did not get what you mean, please let me know how many days of leave you are planning to take")

if __name__ == "__main__":
    main()
