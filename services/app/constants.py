import datetime

MAX_UNBLOCK_WAIT = 30

TEMP = 1

# USER ACTIONS
CONFIRM = 2
CONFIRM_WIHTOUT_VALIDATION = 3
CANCEL = 4


##################################
# JOB STATUSES
##################################

OK = 200
CANCELLED = 201
# PENDING
PENDING = 300   
PENDING_USER_REPLY = 301

USER_ERROR = 400
DURATION_CONFLICT = 401 # TODO
CHANGED = 402
DOUBLE_MESSAGE = 404 # This will always be a job with the single message
FAILED = 500

##################################
# MESSAGE STATUSES
##################################

DELIVERED = 251

# PENDING
PENDING_CALLBACK = 351

####################################

intents = {
    "TAKE_MC": 1,
    "OTHERS": 2,
    "USER_CONFIRMATION": 3,
    "ES_SEARCH": 4
}

messages = {
    "SENT": 1, 
    "RECEIVED": 2,
    "CONFIRM": 3, 
    "FORWARD": 4
}

errors = {
    "USER_NOT_FOUND": "I'm sorry, your contact has not been added to our database. Please check with HR.",
    "PENDING_USER_REPLY": "Please reply to the previous message first, thank you!",
    "DOUBLE_MESSAGE": "Please send only 1 message at a time, thank you!",
    "UNKNOWN_ERROR": "Something went wrong, please send the message again",
    "NO_RECENT_MSG": "I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?",
    "DATES_NOT_FOUND": "The chatbot is still in development, we regret that we could not determine your period of MC, could you specify the dates/duration again?",
    "CONFIRMING_CANCELLED_MSG": "MC has already been cancelled!",
    "NO_RELATIONS": "Really sorry, there doesn't seem to be anyone to inform about your MC. Please contact the school HR.",
    "WRONG_DATE": "I'm sorry, if I got the dates and duration wrong, please send it to me again!",
    "ES_REPLY_ERROR": "The chatbot is still in development, we regret that we could not determine your intent. If you need additional help, please reach out to our new helpline 87178103.",
    "AZURE_SYNC_ERROR": "I'm sorry, something went wrong with the code, please check with ICT.",
    "ALL_DUPLICATE_DATES": "You are already on MC on all these dates",
    "NOT_LAST_MSG": "To confirm or cancel the MC, please only reply to the latest message!"
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