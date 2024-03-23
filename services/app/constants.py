MAX_UNBLOCK_WAIT = 30

# OTHER STATUSES
CHANGED = 5 # changed dates and start date for MC

##################################
# JOB STATUSES
##################################


PROCESSING = 102
ACCEPTED = 202
CREATED = 201
OK = 200
SERVER_ERROR = 500 # Bad Request

PENDING_USER_REPLY = 301
# PROCESSING MSG CALLBACK
PENDING_CALLBACK = 302

# ERROR JOB STATUS
CLIENT_ERROR = 401
SERVER_ERROR = 402
# DURATION_CONFLICT = 403 # TODO
DOUBLE_MESSAGE = 409 # Conflict This will always be a job with a single message


####################################
# leave_job_status = {
#     "PROCESSING": PROCESSING, 
#     "PENDING_USER_REPLY": PENDING_USER_REPLY, 
#     "ACCEPTED": ACCEPTED,
#     "CREATED": CREATED,
#     "OK": OK
# } # → Processing, Pending User Reply, Accepted (Db), Ok (Forwards)

DECISIONS = {
    'CONFIRM': '1',
    'CANCEL': '2',
}

leave_types = {
    "Medical": ["medical leave", "ml"],
    "Childcare": ["childcare leave", "child care leave", "ccl"],
    "Parentcare": ["parentcare leave", "parent care leave", "pcl"],
    "Hospitalisation": ["hospitalisation leave", "hospitalization leave", "hl"],
    "Compassionate": ["compassionate leave", "cl"],
    # "Paternity": ["paternity leave"],
    # "Maternity": ['maternity leave'],
    # "Anniversary": ['birthday leave', 'wedding leave', 'anniversary leave'],
    # "Marriage": ['marriage leave']
}

MC_DECISIONS = {str(index + 1): key for index, key in enumerate(leave_types.keys())}


# MC_DECISIONS[str(len(leave_types) + 1)] = 'Others'
# MC_DECISIONS IS NOW LIKE A CV DICTIONARY, FROM '1' TO '10'



leave_keywords = r'(' + '|'.join([keyword for keywords in leave_types.values() for keyword in keywords]) + ')'
leave_alt_words = r'(leave|mc|appointment|sick|doctor|medical cert|medical certificate)'

intents = {
    "TAKE_LEAVE": 1,
    "CANCEL_LEAVE": 2,
    "TAKE_LEAVE_NO_TYPE": 3,
    "SHAREPOINT_ADD_RECORD": 4,
    "SHAREPOINT_DEL_RECORD": 5,
    "OTHERS": 6,
    "ES_SEARCH": 7,
    "SEND_ERROR_MESSAGE": 8
}

messages = {
    "SENT": 1, 
    "RECEIVED": 2,
    "CONFIRM": 3,
    "FORWARD": 4
}


system = {
    "MAIN": 1,
    "SYNC_USERS": 2,
    "INDEX_DOCUMENT": 3,
    "AM_REPORT": 4,
    "ACQUIRE_TOKEN": 5,
    "SYNC_LEAVE_RECORDS": 6
}

METRIC_MAPPING = {index + 1: key for index, key in enumerate(system.keys())}

metric_names = {
    "LAST_AZURE_SYNC": "LAST_AZURE_SYNC",
    "LAST_LOCAL_DB_UPDATE": "LAST_LOCAL_DB_UPDATE"
}

errors = {
    "USER_NOT_FOUND": "I'm sorry, your contact is not in our database. Please check with HR and try again in an hour.",
    "PENDING_USER_REPLY": "Please reply to the previous message first, thank you!",
    "DOUBLE_MESSAGE": "The previous job has not completed or there was an error completing it. If the problem persists, please try again in 2 minutes, thank you!",
    "UNKNOWN_ERROR": "Something went wrong, please send the message again",
    "NO_RECENT_MSG": "I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?",
    "DATES_NOT_FOUND": "The chatbot is still in development, we regret that we could not determine your period of MC, could you specify the dates/duration again?",
    "CONFIRMING_CANCELLED_MSG": "MC has already been cancelled!",
    "NO_RELATIONS": "Really sorry, there doesn't seem to be anyone to inform about your MC. Please contact the school HR.",
    "WRONG_DATE": "I'm sorry, if I got the dates and duration wrong, please send it to me again!",
    "ES_REPLY_ERROR": "The chatbot is still in development, we regret that we could not determine your intent. If you need additional help, please reach out to our new helpline 87178103.",
    "AZURE_SYNC_ERROR": "I'm sorry, something went wrong with the code, please check with ICT.",
    "ALL_DUPLICATE_DATES": "You are already on leave for all these dates",
    "NOT_LAST_MSG": "To confirm or cancel the leave, please only reply to the latest message!",
    "MESSAGE_STILL_PENDING": "Sorry, please try again in a few seconds, a message sent to you is still pending success confirmation.",
    "JOB_LEAVE_FAILED": "Sorry, it seems like there is no records of this job in the database.",
    "MC_WRONG_SYNTAX": "Sorry, the message should specify the type of leave. Possible values: medical leave, ml, childcare leave, child care leave, ccl, parentcare leave, parent care leave, pcl, hospitalization leave, hospitalisation leave, hl, compassionate leave, cl",
    "NO_DEL_DATE": "Sorry, there are no dates left to delete.",
    "TIMEOUT_MSG": "Sorry, it seems like the previous message timed out.",
    "JOB_FAILED_MSG": "Sorry, the previous job has failed.",
    "SENT_MESSAGE_MISSING": "Sorry, it seems like we could not find the relavant job",
    "JOB_COMPLETED": "Sorry, the job has either completed or has failed."
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