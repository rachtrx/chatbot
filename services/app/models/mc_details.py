from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, month_mapping, day_mapping, TEMP, days_arr, PENDING_CALLBACK, FAILED
import re
from dateutil.relativedelta import relativedelta
from twilio.rest import Client
import os
import json


from .forward_details import ForwardDetails
from .message import Message
from .user import User
from .exceptions import DatesMismatchError, ReplyError

from utilities import loop_relations, join_with_commas_and

#IMPT SECTION possible to create an interface for time?

class McDetails(Message):

    #TODO other statuses eg. wrong duration

    __tablename__ = "mc_details"
    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True) # TODO on delete cascade?
    _start_date = db.Column(db.String(20), nullable=True)
    _end_date = db.Column(db.String(20), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    

    __mapper_args__ = {
        "polymorphic_identity": "mc_details"
    }

    @property
    def start_date(self):
        return datetime.strptime(self._start_date, "%d/%m/%Y") if self._start_date is not None else None

    @start_date.setter
    def start_date(self, value):
        self._start_date = datetime.strftime(value, "%d/%m/%Y")

    @property
    def end_date(self):
        return datetime.strptime(self._end_date, "%d/%m/%Y") if self._end_date is not None else None

    @end_date.setter
    def end_date(self, value):
        self._end_date = datetime.strftime(value, "%d/%m/%Y")

    def __init__(self, sid, number, body, intent=intents['TAKE_MC']):
        name = User.get_user(number).name
        timestamp = datetime.now()
        super().__init__(sid, name, body, intent, TEMP, timestamp)
        db.session.add(self)
        db.session.commit()
    
    def generate_base(self):
        '''Generates the basic details of the MC, including the start, end and duration of MC'''
        # self.duration is extracted duration
        self.duration = int(self.duration_extraction()) if self.duration_extraction() else None
        duration_c = self.set_start_end_date() # checks for conflicts and sets the dates

        print("start generate_base")
        
        if duration_c:
            # if there are specified dates and no duration
            print(self.end_date, self.duration, duration_c, self.start_date)
            if self.duration == None:
                self.duration = duration_c
            # if there are specified dates and duration is wrong
            elif self.duration and self.duration != duration_c:
                raise DatesMismatchError(f"The durations do not match! Did you mean {duration_c} days?") #TODO fix this!
            
        # if there is only 1 specified date and duration_e
        elif self.duration and self.start_date:
            self.end_date = self.start_date + timedelta(days=max(int(self.duration) - 1, 0))

        #note: if end date and duration, start date is assumed to be today and duration error would have been flagged out
        elif self.start_date:
            self.end_date = self.start_date
            self.duration = 1

        # only duration e and no dates
        else: 
            try: # duration specified
                self.calc_start_end_date(self.duration) # sets self.start_date, self.end_date
            except TypeError: # start, end dates and duration not specified
                return False
            
        print("Generate base working")
        
        return True
    
    def set_start_end_date(self):
        '''This function takes in a mc_message and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = self.named_month_extraction()
        ddmm_start, ddmm_end = self.named_ddmm_extraction()
        print(f'ddmm_end: {ddmm_end}')
        day_start, day_end = self.named_day_extraction()
        
        start_dates = [date for date in [named_month_start, ddmm_start, day_start] if date is not None]
        end_dates = [date for date in [named_month_end, ddmm_end, day_end] if date is not None]

        print(start_dates, end_dates)

        if len(start_dates) > 1:
            raise DatesMismatchError(f"Conflicting start dates {', '.join(str(date) for date in start_dates)}")
        if len(end_dates) > 1:
            raise DatesMismatchError(f"Conflicting end dates {', '.join(str(date) for date in start_dates)}")
        
        if len(start_dates) == 1:
            self.start_date = start_dates[0]
        if len(end_dates) == 1:
            self.end_date = end_dates[0]
        
        if self.start_date and self.end_date:
            # try:
            return self.duration_calc() # returns duration_c
            # except:
            #     return False
        
        return None

    def match_start_end_date(self, match_obj, date_format):
        '''returns date'''
        print("matching dates")
        date = None
        print(match_obj.group("date"), match_obj.group("month"))
        if match_obj.group("date") and match_obj.group("month"):
            date = f'{match_obj.group("date")} {match_obj.group("month")} {datetime.now().year}'
            date = datetime.strptime(date, date_format).date() # create datetime object

        return date
    


    #SECTION 
    def named_ddmm_extraction(self):
        '''Check for normal date pattern ie. 11/11 or something'''

        date_pattern = r'[12][0-9]|3[01]|0?[1-9]'
        month_pattern = r'1[0-2]|0?[1-9]'
        # full_ddmm_pattern = r'(' + date_pattern + r')/(' + month_pattern + r')'

        date_pattern = r'(?P<date>' + date_pattern + r')/(?P<month>' + month_pattern + r')'

        normal_start_date_pattern = r'((from|on)\s' + date_pattern + r')' 
        normal_end_date_pattern = r'((to|until|til(l)?)\s' + date_pattern + r')'


        compiled_start_date_pattern = re.compile(normal_start_date_pattern, re.IGNORECASE)
        compiled_end_date_pattern = re.compile(normal_end_date_pattern, re.IGNORECASE)


        match_start_dates = compiled_start_date_pattern.search(self.body)
        match_end_dates = compiled_end_date_pattern.search(self.body)

        start_date = end_date = None

        # try:
        if match_start_dates:
            start_date = self.match_start_end_date(match_start_dates, "%d %m %Y")
        if match_end_dates:
            end_date = self.match_start_end_date(match_end_dates, "%d %m %Y")
            if start_date == None:
                start_date = datetime.now().date()

        return (start_date, end_date)
        
        #     else:
        #         return (None, None)
        # except TypeError:
        #     return (None, None)

    # TODO CAN MOVE? VERY GENERIC
    @staticmethod
    def replace_with_full_month(match):
        '''pass in the match object from the sub callback and return the extended month string'''
        # Get the matched abbreviation or full month name
        month_key = match.group(0).lower()
        # Return the capitalized full month name from the dictionary
        return month_mapping[month_key]

    def named_month_extraction(self):
        '''Check for month pattern ie. 11 November or November 11'''
        user_str = re.sub(r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b', self.replace_with_full_month, self.body, flags=re.IGNORECASE)

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
                start_date = self.match_start_end_date(start_match_dates, "%d %B %Y")
            if end_match_dates:
                end_date = self.match_start_end_date(end_match_dates, "%d %B %Y")
                if start_date == None:
                    start_date = datetime.now().date()
            return (start_date, end_date)

        dates = get_dates(start_date_pattern, end_date_pattern) # try first pattern
        
        if len([date for date in dates if date is not None]) > 0:
            return dates
        else:
            dates = get_dates(start_date_pattern_2, end_date_pattern_2) # try 2nd pattern
            return dates
        


    # SECTION the functions after these check for dates
    def duration_extraction(self):
        '''ran always to check if user gave any duration'''
        duration_pattern = r'(?P<duration1>\d\d?\d?|a)'
        alternative_duration_pattern = r'(?P<duration2>\d\d?\d?|a)'
        day_pattern = r'(day|days)'
        action_pattern = r'(leave|mc|appointment)'

        # Combine the basic patterns into two main alternatives
        alternative1 = duration_pattern + r'\s.*?' + day_pattern + r'\s.*?' + action_pattern
        alternative2 = action_pattern + r'\s.*?' + alternative_duration_pattern + r'\s.*?' + day_pattern

        # Combine the two main alternatives into the final pattern
        urgent_absent_pattern = re.compile(r'\b(?:on|taking|take) (' + alternative1 + r'|' + alternative2 + r')\b', re.IGNORECASE)

        match_duration = urgent_absent_pattern.search(self.body)
        if match_duration:
            duration = match_duration.group("duration1") or match_duration.group("duration2")
            print(f'duration: {duration}')
            return duration

        return None

    def duration_calc(self):
        '''ran when start_date and end_date is True, returns duration between self.start_time and self.end_time. 
        if duration is negative, it adds 1 to the year. also need to +1 to duration since today is included as well'''

        duration = (self.end_date - self.start_date).days + 1
        if duration < 0:
            self.end_date += relativedelta(years=1)
            duration = (self.end_date - self.start_date).days + 1

        print(f'duration: {duration}')

        return duration

    
    def calc_start_end_date(self, duration):
        '''ran when start_date and end_date is False; takes in extracted duration and returns the calculated start and end date. need to -1 since today is the 1st day. This function is only used if there are no dates. It does not check if dates are correct as the duration will be assumed to be wrong'''
        print("manually calc days")
        print(self.duration)
        self.start_date = datetime.now().date()
        self.end_date = (self.start_date + timedelta(days=int(duration) - 1))

        return None
    
    @staticmethod
    def resolve_day(day_key):
        today = date.today()
        today_weekday = today.weekday()

        if day_key in ['today', 'tdy']:
            return days_arr[today_weekday] # today
        else:
            return days_arr[today_weekday + 1] # tomorrow

    
    def replace_with_full_day(self, match):
        '''pass in the match object from the sub callback and return the extended month string'''
        # Get the matched abbreviation or full month name
        prefix = match.group('prefix') + (' ' + match.group('offset') if match.group('offset') is not None else '')
        day_key = match.group('days').lower()
        print(prefix)

        if day_key in ['today', 'tomorrow', 'tmr', 'tdy']:
            return prefix + ' ' + self.resolve_day(day_key)
        
        # Return the capitalized full month name from the dictionary
        return prefix + ' ' + day_mapping[day_key]

    def named_day_extraction(self):
        '''checks the body for days, returns (start_date, end_date)'''

        start_prefixes = r'from|on|for|mc|starting|doctor'
        end_prefixes = r'to|until|til(l)?|ending'


        # ignore all the "this", it will be handled later
        user_str = re.sub(r'\b(?P<prefix>' + start_prefixes + r'|' + end_prefixes + r')\s*(this)?\s*(?P<offset>next|nx)?\s(?P<days>mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|today|tomorrow|tmr|tdy)\b', self.replace_with_full_day, self.body, flags=re.IGNORECASE)

        print(user_str)

        # done fixing the day names
        days_pattern = r'Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday'
        start_day_pattern = r'(' + start_prefixes + r')\s*(?P<start_buffer>next|nx)?\s(?P<start_day>' + days_pattern + r')'
        end_day_pattern = r'(' + end_prefixes + r')\s*(?P<end_buffer>next|nx)?\s(?P<end_day>' + days_pattern + r')'

        compiled_start_day_pattern = re.compile(start_day_pattern, re.IGNORECASE)
        compiled_end_day_pattern = re.compile(end_day_pattern, re.IGNORECASE)

        start_days = compiled_start_day_pattern.search(user_str)
        end_days = compiled_end_day_pattern.search(user_str)

        start_week_offset = 0
        end_week_offset = 0

        start_day = end_day = None

        if start_days:
            start_week_offset = 0
            start_buffer = start_days.group("start_buffer") # retuns "next" or None
            start_day = start_days.group("start_day")
            print(f'start buffer: {start_buffer}')
            if start_buffer != None:
                start_week_offset = 1

        if end_days:
            end_week_offset = 0
            end_buffer = end_days.group("end_buffer") # retuns "next" or None
            end_day = end_days.group("end_day")
            print(f'end buffer: {end_buffer}')
            if end_buffer != None:
                end_week_offset = 1
                end_week_offset -= start_week_offset

        if start_day == None and end_day == None:
            return (None, None)

        return self.get_future_date(start_day, end_day, start_week_offset, end_week_offset) # returns (start_date, end_date)

        
    def get_future_date(self, start_day, end_day, start_week_offset, end_week_offset):
        today = date.today()
        today_weekday = today.weekday()

        if start_day != None:
            start_day = days_arr.index(start_day)
            if today_weekday > start_day:
                diff = 7 - today_weekday + start_day
                if start_week_offset > 0:
                    start_week_offset -= 1
                # if end_week_offset > 0:
                #     end_week_offset -= 1 #TODO TEST
            else:
                print(start_week_offset, end_week_offset)
                diff = start_day - today_weekday
            start_date = today + timedelta(days=diff + 7 * start_week_offset)
            
        else:
            start_day = today_weekday # idea of user can give the until day without start day and duration
            start_date = today
            
        if end_day != None:
            end_day = days_arr.index(end_day)
            if start_day > end_day:
                diff = 7 - start_day + end_day
                if end_week_offset > 0:
                    end_week_offset -= 1
            else:
                diff = end_day - start_day
            print(end_week_offset)
            end_date = start_date + timedelta(days=diff + 7 * end_week_offset)
        else:
            end_date = None

        print(start_date, end_date)

        return (start_date, end_date)
    
    def generate_date_data(self):

        def daterange():
            for n in range(self.duration):
                yield self.start_date + timedelta(n)

        details = [[f"'{datetime.strftime(date, '%d/%m/%Y')}", self.name, self.user.dept] for date in daterange()]
        for date, name, dept in details:
            print(date)
        
        return details
    
    def send_message(self, client=None):

        @loop_relations
        def generate_each_message(relation):
            '''This function sets up the details of the forward to HOD and reporting officer message'''
            
            body = f'Hi {relation.name}! This is to inform you that {self.user.name} will be taking {self.duration} days MC from {self.start_date} to {self.end_date}'

            print(f"Type of date in notify: {type(self.start_date)}")

            if client:

                content_variables = json.dumps({
                    '1': relation.name,
                    '2': self.user.name,
                    '3': str(self.duration),
                    '4': datetime.strftime(self.start_date, "%d/%m/%Y"),
                    '5': datetime.strftime(self.end_date, "%d/%m/%Y")
                })

                print(content_variables)

                # Send the message
                message = client.messages.create(
                    to='whatsapp:+65' + str(relation.number),
                    from_=os.environ.get("MESSAGING_SERVICE_SID"),
                    content_sid=os.environ.get("MC_NOTIFY_SID"),
                    content_variables=content_variables,
                    # status_callback=os.environ.get("CALLBACK_URL")
                )

                new_message = ForwardDetails(message.sid, self.sid, relation.name, self.user.name, body)
                return new_message

            else:
                return body # local
        
        messages_list = generate_each_message(self.user)
        print(f'Messages List: {messages_list}')
        return messages_list
    
    
    def generate_reply(self, client):
        '''This function gets a mc_details object and returns a confirmation message'''

        print(f"Type of date in confirm: {type(self.start_date)}")

        # statement = f"Hi {self.user.name}, Kindly confirm that you are on MC for {self.duration} days from {datetime.strftime(self.start_date, '%d/%m/%Y')} to {datetime.strftime(self.end_date, '%d/%m/%Y')}. I will help you to inform "

        @loop_relations
        def generate_each_relation(relation):

            # return [relation.name, str(relation.number)]
            return [relation.name, str(relation.number)]
        
        data_list = generate_each_relation(self.user)

        if data_list == None:
            return None

        # list of return statements
        # else:
        #     statement += join_with_commas_and(data_list)

        content_variables = {
            '1': self.user.name,
            '2': str(self.duration),
            '3': datetime.strftime(self.start_date, '%d/%m/%Y'),
            '4': datetime.strftime(self.end_date, '%d/%m/%Y'),
        }

        count = 5
        if len(data_list) > 0:
            for name, number in data_list:
                content_variables[str(count)] = name
                content_variables[str(count + 1)] = number
                count += 2

            content_variables = json.dumps(content_variables)

            message = client.messages.create(
                    to='whatsapp:+65' + str(self.user.number),
                    from_=os.environ.get("MESSAGING_SERVICE_SID"),
                    content_sid=os.environ.get("MC_CONFIRMATION_CHECK_SID"),
                    content_variables=content_variables
                )

            return message

        return None

        
        # print(message.body)

        # statement = f"Hi, Kindly confirm that you are on MC for {self.duration} days from {datetime.strftime(self.start_date, '%d/%m/%Y')} to {datetime.strftime(self.end_date, '%d/%m/%Y')}. I will help you to inform your RO and HOD"
        
            # return statement