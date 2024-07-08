from enum import Enum

import re

class LeaveType(Enum):
    MEDICAL = "MEDICAL"
    CHILDCARE = "CHILDCARE"
    PARENTCARE = "PARENTCARE"
    HOSPITALISATION = "HOSPITALISATION"
    COMPASSIONATE = "COMPASSIONATE"
    MATERNITY = "MATERNITY"
    PATERNITY = "PATERNITY"
    BIRTHDAY = "BIRTHDAY"
    WEDDING = "WEDDING"
    MARRIAGE = "MARRIAGE"

class Patterns:

    LEAVE_KEYWORDS_DICT = {
        LeaveType.MEDICAL: ["medical leave", "ml", "mc", "medical cert", "medical certificate", "sick", "medical appointment"],
        LeaveType.CHILDCARE: ["childcare leave", "child care leave", "ccl"],
        LeaveType.PARENTCARE: ["parentcare leave", "parent care leave", "pcl"],
        LeaveType.HOSPITALISATION: ["hospitalisation leave", "hospitalization leave", "hl"],
        LeaveType.COMPASSIONATE: ["compassionate leave", "cl"],
        LeaveType.PATERNITY: ["paternity leave"],
        LeaveType.MATERNITY: ['maternity leave'],
        LeaveType.BIRTHDAY: ['birthday leave', 'anniversary leave'], # TODO
        LeaveType.WEDDING: ['wedding leave', 'anniversary leave'],
        LeaveType.MARRIAGE: ['marriage leave']
    }

    LEAVE_KEYWORDS = re.compile(
        r'(' + '|'.join([keyword for keywords in LEAVE_KEYWORDS_DICT.values() for keyword in keywords]) + ')',
        re.IGNORECASE
    )
    LEAVE_ALT_WORDS = r'(leave|appointment|mc|ml|sick|medical certificate|medical cert|ccl|pcl|hl|cl)'

    START_PREFIXES = r'from|on|for|starting|doctor|leave|mc|appointment|sick|doctor|ml|ccl|npl|medical cert|medical certificate'
    END_PREFIXES = r'to|until|til|till|ending'
    MONTHS_LOOSE = r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b'
    MONTHS_STRICT = r'January|February|March|April|May|June|July|August|September|October|November|December'
    
    # SECTION 1. eg. 5 December OR December 5
    DATE_PATTERN = r'(?P<date>\d{1,2})(st|nd|rd|th)?'
    MONTH_PATTERN = r'(?P<month>' + MONTHS_STRICT + r')'

    DATE_FIRST_PATTERN = DATE_PATTERN + r'\s*' + MONTH_PATTERN
    MONTH_FIRST_PATTERN = MONTH_PATTERN + r'\s*' + DATE_PATTERN

    START_DATE_PATTERN = re.compile(
        r'(' + START_PREFIXES + ')\s(' + DATE_FIRST_PATTERN + r')',
        re.IGNORECASE
    )
    END_DATE_PATTERN = re.compile(
        r'(' + END_PREFIXES + ')\s(' + DATE_FIRST_PATTERN + r')',
        re.IGNORECASE
    )

    START_DATE_PATTERN_2 = re.compile(
        r'(' + START_PREFIXES + ')\s(' + MONTH_FIRST_PATTERN + r')',
        re.IGNORECASE
    )
    END_DATE_PATTERN_2 = re.compile(
        r'(' + END_PREFIXES + ')\s(' + MONTH_FIRST_PATTERN + r')',
        re.IGNORECASE
    )

    # SECTION 2. 5/12 
    DD = r'[12][0-9]|3[01]|0?[1-9]'
    MM = r'1[0-2]|0?[1-9]'
    DDMM = r'(?P<date>' + DD + r')/(?P<month>' + MM + r')'

    DDMM_START_DATE = re.compile(
        r'(' + START_PREFIXES + r')\s(' + DDMM + r')',
        re.IGNORECASE
    )
    DDMM_END_DATE = re.compile(
        r'(' + END_PREFIXES + r')\s(' + DDMM + r')',
        re.IGNORECASE
    )


    # SECTION 3. 5 days leave OR leave for 5 days
    DURATION = r'(?P<duration1>\d\d?\d?|a)'
    DURATION_2 = r'(?P<duration2>\d\d?\d?|a)' # need to have both so that can be compiled together (otherwise it will be rejected in that OR)
    DAY = r'(day|days)'

    LEAVE_TYPE_MAX_TWO_WORDS = r'(\b\w+\b\s+){0,2}'

    # Combine the basic patterns into two main alternatives. use the loose keywords for this, in case its a retry. if first try, allow max 2 words before "leave"
    DURATION_PATTERN_1 = DURATION + r'\s.*?' + DAY + r'\s.*?' + LEAVE_TYPE_MAX_TWO_WORDS + LEAVE_ALT_WORDS
    DURATION_PATTERN_2 = LEAVE_TYPE_MAX_TWO_WORDS + LEAVE_ALT_WORDS + r'\s.*?' + DURATION_2 + r'\s.*?' + DAY

    # Combine the two main alternatives into the final pattern
    DURATION_PATTERN = re.compile(
        r'\b.*?(?:on|taking|take) (' + DURATION_PATTERN_1 + r'|' + DURATION_PATTERN_2 + r')\b',
        re.IGNORECASE
    )

    # SECTION 4. next tues
    # ignore all the "this", it will be handled later. 
    DAYS_OF_WEEK_PATTERN = r'\b(?P<prefix>' + START_PREFIXES + r'|' + END_PREFIXES + r')\s*(this)?\s*(?P<offset>next|nx)?\s(?P<days>mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|today|tomorrow|tmr|tdy)\b' # required to alter user string

    # done fixing the day names
    DAYS_OF_WEEK = r'Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday'
    NEGATIVE_LOOKBEHINDS = r"(?<!" + r"\s)(?<!".join(END_PREFIXES.split('|')) + r"\s)"

    START_DAY_PATTERN = re.compile(
        rf'\s(?:{START_PREFIXES}|{NEGATIVE_LOOKBEHINDS}(?P<start_buffer>next|nx))*\s(?P<start_day>{DAYS_OF_WEEK})',
        re.IGNORECASE
    )
    END_DAY_PATTERN = re.compile(
        r'(?:' + END_PREFIXES + r')\s*(?P<end_buffer>next|nx)?\s(?P<end_day>' + DAYS_OF_WEEK + r')',
        re.IGNORECASE
    )

    MONTH_MAPPING = {
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

    DAY_MAPPING = {
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

    DAYS_STRICT = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

class LeaveErrorMessage:
    REGEX = "Sorry, I got the dates and duration wrong."
    CONFIRMING_CANCELLED_MSG = "Leave has already been cancelled!"
    ALL_OVERLAPPING = "You are already on leave for all these dates."
    NO_DATES_TO_APPROVE = "No dates were found past 9am today that are still pending approval."
    NO_DATES_TO_CANCEL = "No dates were found past 9am today that are still active."
    NO_DATES_TO_REJECT = "No dates were found past 9am today that are still active."
    AUTHORISING_CANCELLED_MSG = "Leave has already been cancelled!"
    LEAVE_CANCELLED = "Leave has already been cancelled!"
    LEAVE_APPROVED = "Leave has already been approved!"
    LEAVE_REJECTED = "Leave has already been rejected!"
    REQUEST_EXPIRED = "This request has expired."
    NO_USERS_TO_NOTIFY = "No staff found to forward message to. Please contact the school HR."

class LeaveError(Enum):
    REGEX = 'REGEX'
    ALL_OVERLAPPING = 'ALL_OVERLAPPING'
    ALL_PREVIOUS_DATES = 'ALL_PREVIOUS_DATES'
    DURATION_MISMATCH = 'DURATION_MISMATCH'
    DATES_NOT_FOUND = 'DATES_NOT_FOUND'
    NO_USERS_TO_NOTIFY = 'NO_USERS_TO_NOTIFY'
    TIMEOUT = 'TIMEOUT'
    UNKNOWN = 'UNKNOWN'

class LeaveIssue(Enum): # ERRORS THAT CAN BE FIXED
    UPDATED = "I am unable to add leaves before today; the earliest date is today." # start date was even before today and was accepted nonetheless; need to inform user about dates change
    LATE = "You have missed out the morning report for today's leave as it has already been sent out at 9am, but I am still able to update the records and inform your reporting contacts." # start date was today, need to inform user about missed morning report
    OVERLAP = "There are overlapping dates on "

class LeaveTaskType(Enum):
    NONE = 'NONE'
    EXTRACT_DATES = 'EXTRACT_DATES'
    REQUEST_CONFIRMATION = 'REQUEST_CONFIRMATION'
    REQUEST_AUTHORISATION = 'REQUEST_AUTHORISATION'
    APPROVE = 'APPROVE'
    REJECT = 'REJECT'
    CANCEL = 'CANCEL'

class LeaveStatus(Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"



