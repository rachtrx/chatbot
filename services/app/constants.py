import datetime

TEMP = 1

# USER ACTIONS
CONFIRM = 2
CANCEL = 3

##################################
# JOB STATUSES
##################################

COMPLETE = 200
USER_ERROR = 400
DURATION_CONFLICT = 401 # TODO
DOUBLE_MESSAGE = 402 # This will always be a job with the single message
FAILED = 500

# PENDING
PENDING_USER_REPLY = 301


##################################
# MESSAGE STATUSES
##################################

# REPLY STATUSES
REPLY_SENT = 201
ERROR_SENT = 202
REPLY_FAILED = 501
ERROR_FAILED = 502

# FORWARD_STATUSES
FORWARD_SENT = 203
FORWARD_FAILED = 503

# PENDING
PENDING_REPLY_STATUS_PENDING_USER_REPLY = 302

####################################

# PENDING FOR BOTH
PENDING_REPLY_STATUS = 300
PENDING_FORWARD_STATUS = 303
PENDING_ERROR_REPLY_STATUS = 304

intents = {
    "TAKE_MC": 1,
    "OTHERS": 2,
    "USER_CONFIRMATION": 3,
    "ES_SEARCH": 4
}

errors = {
    "USER_NOT_FOUND": "I'm sorry, your contact has not been added to our database. Please check with HR.",
    "PENDING_USER_REPLY": "Please reply to the previous message first, thank you!",
    "DOUBLE_MESSAGE": "Please send only 1 message at a time, thank you!",
    "CONFIRMING_CANCELLED_MSG": "MC has already been cancelled!",
    "UNKNOWN_ERROR": "Something went wrong, please send the message again",
    "NO_RECENT_MSG": "I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?",
    "DATES_NOT_FOUND": "The chatbot is still in development, we regret that we could not determine your period of MC, could you specify the dates/duration again?",
    "NO_RELATIONS": "Really sorry, there doesn't seem to be anyone to inform about your MC. Please contact the school HR.",
    "WRONG_DATE": "I'm sorry, if I got the dates and duration wrong, please send it to me again!",
    "ES_REPLY_ERROR": "The chatbot is still in development, we regret that we could not determine your intent. If you need additional help, please reach out to our new helpline 87178103.",
    "AZURE_SYNC_ERROR": "I'm sorry, something went wrong with the code, please check with ICT."
}


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

days_arr = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

day_mapping = {
    'mon': 'Monday',
    'monday': 'Monday',
    'tue': 'Tuesday',
    'tues': 'Tuesday',
    'tuesday': 'Tuesday',
    'wed': 'Wednesday',
    'wednesday': 'Wednesday',
    'thu': 'Thursday',
    'thurs': 'Thursday',
    'thursday': 'Thursday',
    'fri': 'Friday',
    'friday': 'Friday',
    'sat': 'Saturday',
    'saturday': 'Saturday',
    'sun': 'Sunday',
    'sunday': 'Sunday',
}

####################################
# REGULAR EXPRESSIONS
####################################

# utilities

start_prefixes = r'from|on|for|mc|starting|doctor'
end_prefixes = r'to|until|til(l)?|ending'

# 1. eg. 5 December OR December 5
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


# 2. 5/12 

dd_pattern = r'[12][0-9]|3[01]|0?[1-9]'
mm_pattern = r'1[0-2]|0?[1-9]'

ddmm_pattern = r'(?P<date>' + dd_pattern + r')/(?P<month>' + mm_pattern + r')'

ddmm_start_date_pattern = r'(' + start_prefixes + r')\s(' + ddmm_pattern + r')' 
ddmm_end_date_pattern = r'(' + end_prefixes + r')\s(' + ddmm_pattern + r')'


# 3. 5 days mc OR mc for 5 days
duration_pattern = r'(?P<duration1>\d\d?\d?|a)'
alternative_duration_pattern = r'(?P<duration2>\d\d?\d?|a)' # need to have both so that can be compiled together (otherwise it will be rejected in that OR)
day_pattern = r'(day|days)'
mc_pattern = r'(leave|mc|appointment|sick|doctor)'

# Combine the basic patterns into two main alternatives
alternative1 = duration_pattern + r'\s.*?' + day_pattern + r'\s.*?' + mc_pattern
alternative2 = mc_pattern + r'\s.*?' + alternative_duration_pattern + r'\s.*?' + day_pattern

# Combine the two main alternatives into the final pattern
final_duration_extraction = r'\b(?:on|taking|take) (' + alternative1 + r'|' + alternative2 + r')\b'


# 4. next tues
# ignore all the "this", it will be handled later. 
days_regex = r'\b(?P<prefix>' + start_prefixes + r'|' + end_prefixes + r')\s*(this)?\s*(?P<offset>next|nx)?\s(?P<days>mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|today|tomorrow|tmr|tdy)\b' # required to alter user string

# done fixing the day names
days_pattern = r'Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday'
start_day_pattern = r'(' + start_prefixes + r')\s*(?P<start_buffer>next|nx)?\s(?P<start_day>' + days_pattern + r')'
end_day_pattern = r'(' + end_prefixes + r')\s*(?P<end_buffer>next|nx)?\s(?P<end_day>' + days_pattern + r')'