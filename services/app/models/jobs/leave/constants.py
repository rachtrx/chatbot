from enum import Enum

import re

from models.jobs.base.constants import Constants

AM_HOUR = 9
PM_HOUR = 17

class LeaveType:
    
    _id_map = {}
    _attr_map = {}

    def __init__(self, id, name, keywords):
        self.id = id
        self.name = name
        self.keywords = keywords

        LeaveType._id_map[id] = self

    def __repr__(self):
        return f"<LeaveType(id='{self.id}', name='{self.name}')>"
    
    @classmethod
    def get_ids(cls):
        return cls._id_map.keys()

    @classmethod
    def get_by_id(cls, id):
        return cls._id_map.get(id)
    
    @classmethod
    def get_by_attr(cls, attr):
        return cls._attr_map.get(attr)
    
    @classmethod
    def convert_attr_to_text(cls, attr):
        leave_type = cls._attr_map.get(attr)
        return leave_type.name if leave_type else attr

    @classmethod
    def assign_attr_names(cls):
        for attr_name, leave_type in vars(cls).items():
            if isinstance(leave_type, LeaveType):
                leave_type.attr_name = attr_name
                cls._attr_map[attr_name] = leave_type
        return list(cls._attr_map.values())


# Data for each leave type
LeaveType.ADOPTION = LeaveType(
    id="LT_1", 
    name="Adoption", 
    keywords=["adoption leave"]
)
LeaveType.ANNUAL = LeaveType(
    id="LT_2", 
    name="Annual", 
    keywords=["annual leave"]
)
LeaveType.BIRTHDAY_WEDDING = LeaveType(
    id="LT_3", 
    name="Birthday/Wedding", 
    keywords=["birthday leave", "wedding leave", "anniversary leave"]
)
LeaveType.CHILDCARE = LeaveType(
    id="LT_4", 
    name="Childcare", 
    keywords=["childcare leave", "child care leave", "ccl"]
)
LeaveType.CHILDCARE_W_MC = LeaveType(
    id="LT_5", 
    name="Childcare with MC", 
    keywords=["childcare with mc", "childcare leave with mc", "childcare with mc leave"]
)
LeaveType.COMPASSIONATE = LeaveType(
    id="LT_6", 
    name="Compassionate", 
    keywords=["compassionate leave", "cl"]
)
LeaveType.CONVOCATION = LeaveType(
    id="LT_7", 
    name="Convocation", 
    keywords=["convocation leave", "convocation"]
)
LeaveType.EXAMINATION = LeaveType(
    id="LT_8", 
    name="Examination", 
    keywords=["examination leave", "exam leave", "exam", "exams"]
)
LeaveType.HOSPITALISATION = LeaveType(
    id="LT_9", 
    name="Hospitalisation", 
    keywords=["hospitalisation leave", "hospitalization leave", "hl"]
)
LeaveType.INFANTCARE = LeaveType(
    id="LT_10", 
    name="Infant Care", 
    keywords=["infant care leave", "infantcare leave", "infantcare"]
)
LeaveType.MARRIAGE = LeaveType(
    id="LT_11", 
    name="Marriage", 
    keywords=["marriage leave"]
)
LeaveType.MARRIAGE_FAMILY = LeaveType(
    id="LT_12", 
    name="Marriage (Family)", 
    keywords=["marriage (family) leave", "marriage family leave", "family marriage leave", "fam marriage leave", "family wedding leave"]
)
LeaveType.MATERNITY = LeaveType(
    id="LT_13", 
    name="Maternity", 
    keywords=["maternity leave", "leaveiversary"]
)
LeaveType.NS = LeaveType(
    id="LT_14", 
    name="National Service", 
    keywords=["ns leave", "ns"]
)
LeaveType.NPL = LeaveType(
    id="LT_15", 
    name="No Pay", 
    keywords=["no pay leave", "npl", "nopay leave", "np leave"]
)
LeaveType.NS_VISITATION = LeaveType(
    id="LT_16", 
    name="NS Camp Visitation", 
    keywords=["ns camp visitation", "ns camp visitation leave", "ns visitation"]
)
LeaveType.OFF_IN_LIEU = LeaveType(
    id="LT_17", 
    name="Off-in-lieu", 
    keywords=["off-in-lieu", "off in lieu leave", "off in lieu"]
)
LeaveType.COURSE = LeaveType(
    id="LT_18", 
    name="Course", 
    keywords=["on course leave", "on course"]
)
LeaveType.PARENTCARE = LeaveType(
    id="LT_19", 
    name="Parentcare", 
    keywords=["parentcare leave", "parent care leave", "pcl"]
)
LeaveType.PATERNITY = LeaveType(
    id="LT_20", 
    name="Paternity", 
    keywords=["paternity leave"]
)
LeaveType.PDL = LeaveType(
    id="LT_21", 
    name="PDL", 
    keywords=["professional development leave", "pdl"]
)
LeaveType.HDB = LeaveType(
    id="LT_22", 
    name="HDB Purchase", 
    keywords=["hdb purchase leave", "hdb leave", "hdb purchasing leave", "buying a hdb", "purchasing a hdb"]
)
LeaveType.REPRESENTATIONAL = LeaveType(
    id="LT_23", 
    name="Representational", 
    keywords=["representational leave"]
)
LeaveType.OVERSEAS = LeaveType(
    id="LT_24", 
    name="Overseas", 
    keywords=["overseas leave", "overseas"]
)
LeaveType.SHARED_PARENTAL = LeaveType(
    id="LT_25", 
    name="Shared Parental", 
    keywords=["shared parental leave"]
)
LeaveType.SICK = LeaveType(
    id="LT_26", 
    name="Sick",
    keywords=["medical leave", "ml", "mc", "medical cert", "medical certificate", "sick", "medical appointment", "sick leave"]
)
LeaveType.SPECIAL = LeaveType(
    id="LT_27", 
    name="Special", 
    keywords=["special leave"]
)
LeaveType.TIME_OFF = LeaveType(
    id="LT_28", 
    name="Time-off", 
    keywords=["time-off"]
)
LeaveType.URGENT_PRIVATE = LeaveType(
    id="LT_29", 
    name="Urgent Private", 
    keywords=["urgent private leave", "private leave", "urgent leave"]
)
LeaveType.WFH = LeaveType(
    id="LT_30", 
    name="Work From Home", 
    keywords=["work from home", "wfh"]
)

ALL_LEAVE_TYPES = LeaveType.assign_attr_names()

class Patterns:

    LEAVE_KEYWORDS = re.compile(
        r'(' + '|'.join([keyword for leave_type in ALL_LEAVE_TYPES for keyword in leave_type.keywords]) + ')',
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
        r'(' + START_PREFIXES + ')\s*(' + DATE_FIRST_PATTERN + r')',
        re.IGNORECASE
    )
    END_DATE_PATTERN = re.compile(
        r'(' + END_PREFIXES + ')\s*(' + DATE_FIRST_PATTERN + r')',
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
    ALL_OVERLAPPING = "You are already on leave for all dates."
    NO_DATES_TO_CANCEL = "No dates were found past 9am today that are still active."
    LEAVE_CANCELLED = "Leave has already been cancelled!"
    LEAVE_CONFIRMED = "Leave has already been confirmed!"
    REQUEST_EXPIRED = "This request has expired."
    NO_USERS_TO_NOTIFY = "No staff found to forward message to. Please contact the school HR."

class LeaveError:
    REGEX = 'REGEX'
    RERAISE = 'RERAISE'
    ALL_OVERLAPPING = 'ALL_OVERLAPPING'
    ALL_PREVIOUS_DATES = 'ALL_PREVIOUS_DATES'
    DURATION_MISMATCH = 'DURATION_MISMATCH'
    DATES_NOT_FOUND = 'DATES_NOT_FOUND'
    NO_USERS_TO_NOTIFY = 'NO_USERS_TO_NOTIFY'
    TIMEOUT = 'TIMEOUT'
    UNKNOWN = 'UNKNOWN'

class LeaveIssue: # ERRORS THAT CAN BE FIXED
    UPDATED = "I am unable to add leaves before today; the earliest date is today." # start date was even before today and was accepted nonetheless; need to inform user about dates change
    LATE = "You have missed out the morning report for today's leave as it has already been sent out at 9am, but I am still able to update the records and inform your reporting contacts." # start date was today, need to inform user about missed morning report
    OVERLAP = "There are overlapping dates on "

class LeaveTaskType:
    NONE = 'NONE'
    EXTRACT_DATES = 'EXTRACT_DATES'
    REQUEST_CONFIRMATION = 'REQUEST_CONFIRMATION'
    CONFIRM = 'CONFIRM'
    CANCEL = 'CANCEL'
    

class LeaveStatus:
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"

class Time:
    AUTO_APPROVAL = '5PM'