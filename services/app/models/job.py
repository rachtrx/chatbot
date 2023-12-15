from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, errors, months_regex, days_regex, ddmm_start_date_pattern, ddmm_end_date_pattern, final_duration_extraction, start_day_pattern, end_day_pattern, month_mapping, day_mapping, days_arr, TEMP, DURATION_CONFLICT, DOUBLE_MESSAGE, PENDING_FORWARD_STATUS, PENDING_USER_REPLY, CONFIRM, CANCEL, COMPLETE, FAILED
import re
from dateutil.relativedelta import relativedelta
import os
import uuid
from utilities import current_sg_time
from config import manager

from constants import mc_pattern, intents
from .exceptions import ReplyError, AzureSyncError
from .message import Message
from .user import User
from .chatbot import Chatbot

# TODO CHANGE ALL MESSAGE TO USER_STR

class Job(db.Model):
    __tablename__ = 'job'
    type = db.Column(db.String(50))
    job_number = db.Column(db.String, primary_key=True)

    name = db.Column(db.String(), db.ForeignKey('user.name', ondelete="CASCADE"), nullable=False)
    # Other job-specific fields
    status = db.Column(db.Integer(), nullable=False)
    created_at = db.Column(db.DateTime, default=current_sg_time())

    user = db.relationship('User', backref='jobs')
    
    __mapper_args__ = {
        "polymorphic_identity": "job",
        "polymorphic_on": "type",
    }

    def __init__(self, name):
        print(f"current time: {current_sg_time()}")
        self.job_number = uuid.uuid4().hex
        self.name = name
        self.created_at = current_sg_time()
        self.status = TEMP
        db.session.add(self)
        db.session.commit()

    @property
    def forwarded_messages(self):

        forwarded_msgs = [msg for msg in self.messages if msg.type == "forward_message"]
        return forwarded_msgs

    @classmethod
    def create_job(cls, intent, sid, first_msg, *args, **kwargs):
        if intent == intents['TAKE_MC']:
            new_job = McJob(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == intents['OTHERS'] or intent == intents['ES_SEARCH']:
            new_job =  cls(*args, **kwargs)
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        new_message = Message(new_job.job_number, sid, first_msg)
        return new_message
    
    def commit_status(self, status):
        '''tries to update status'''
        self.status = status
        # db.session.add(self)
        db.session.commit()

        return True
    
    @classmethod
    def get_recent_message(cls, number):
        '''Returns the user if they have any pending MC message from the user within 1 hour'''
        recent_msg = Message.query.join(cls).join(User).filter(
            User.name == User.get_user(number).name,
            Message.status != DOUBLE_MESSAGE,
            Message.status != PENDING_FORWARD_STATUS
        ).order_by(
            desc(Message.timestamp)
        ).first()
        
        if recent_msg:
            timestamp = recent_msg.timestamp
            current_time = datetime.now()
            time_difference = current_time - timestamp
            print(time_difference)
            if time_difference < timedelta(minutes=5):
                return recent_msg
            
        return None

class McJob(Job):
    __tablename__ = "mc_job"
    job_number = db.Column(db.ForeignKey("job.job_number"), primary_key=True) # TODO on delete cascade?
    _start_date = db.Column(db.String(20), nullable=True)
    _end_date = db.Column(db.String(20), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "mc_job"
    }

    def __init__(self, name):
        super().__init__(name)

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
    
    def generate_base(self, message):
        '''Generates the basic details of the MC, including the start, end and duration of MC'''
        # self.duration is extracted duration
        self.duration = int(self.duration_extraction(message)) if self.duration_extraction(message) else None
        duration_c = self.set_start_end_date(message) # checks for conflicts and sets the dates

        print("start generate_base")
        
        if duration_c:
            # if there are specified dates and no duration
            print(self.end_date, self.duration, duration_c, self.start_date)
            if self.duration == None:
                self.duration = duration_c
            # if there are specified dates and duration is wrong
            elif self.duration and self.duration != duration_c:

                body = f'The duration from {self.start_date} to {self.end_date} ({duration_c}) days) do not match with {self.duration} days. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

                raise ReplyError(body, intents['TAKE_MC'], status=DURATION_CONFLICT) #TODO fix this!
            
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
            
        # TODO if self.start_date is > today 8am, splice out from tomorrow
        # check if theres overlaps on sharepoint

            
        print("Generate base working")
        
        return True
    
    def set_start_end_date(self, message):
        '''This function takes in a mc_message and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = self.named_month_extraction(message)
        ddmm_start, ddmm_end = self.named_ddmm_extraction(message)
        print(f'ddmm_end: {ddmm_end}')
        day_start, day_end = self.named_day_extraction(message)
        
        start_dates = [date for date in [named_month_start, ddmm_start, day_start] if date is not None]
        end_dates = [date for date in [named_month_end, ddmm_end, day_end] if date is not None]

        print(start_dates, end_dates)

        if len(start_dates) > 1:

            body = f'Conflicting start dates {", ".join(str(date) for date in start_dates)}. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise ReplyError(body, intent=intents['TAKE_MC'], status=DURATION_CONFLICT)
        if len(end_dates) > 1:
            
            body = f'Conflicting end dates {", ".join(str(date) for date in end_dates)}. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise ReplyError(body, intent=intents['TAKE_MC'], status=DURATION_CONFLICT)
        
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
    def named_ddmm_extraction(self, mc_message):
        '''Check for normal date pattern ie. 11/11 or something'''

        compiled_start_date_pattern = re.compile(ddmm_start_date_pattern, re.IGNORECASE)
        compiled_end_date_pattern = re.compile(ddmm_end_date_pattern, re.IGNORECASE)

        match_start_dates = compiled_start_date_pattern.search(mc_message)
        match_end_dates = compiled_end_date_pattern.search(mc_message)

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

    def named_month_extraction(self, message):
        '''Check for month pattern ie. 11 November or November 11'''
        user_str = re.sub(months_regex, self.replace_with_full_month, message, flags=re.IGNORECASE)

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
    def duration_extraction(self, message):
        '''ran always to check if user gave any duration'''

        # Combine the two main alternatives into the final pattern
        urgent_absent_pattern = re.compile(final_duration_extraction, re.IGNORECASE)

        match_duration = urgent_absent_pattern.search(message)
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

    def named_day_extraction(self, message):
        '''checks the body for days, returns (start_date, end_date)'''

        # ignore all the "this", it will be handled later
        user_str = re.sub(days_regex, self.replace_with_full_day, message, flags=re.IGNORECASE)

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
    
    def validate_mc_replied_message(self, decision, new_message):

        if self.status == PENDING_USER_REPLY:
            if decision == CONFIRM:
                self.forward_and_update_azure(new_message)
                return
            
            elif decision == CANCEL:
                raise ReplyError(errors['WRONG_DATE'], intent=intents['TAKE_MC'], new_message=new_message)
            
        elif self.status == COMPLETE and decision == CANCEL:
            # TODO CANCEL THE MC
            print("CANCEL THE MC")
            raise ReplyError("This feature hasn't been immplemented yet, sorry!", job_status=CANCEL, new_message=new_message)

        elif self.status == FAILED and decision == CONFIRM:
            raise ReplyError(errors['CONFIRMING_CANCELLED_MSG'], new_message=new_message)

        else: # TODO IMPT need to wait awhile first!
            raise ReplyError(errors['UNKNOWN_ERROR'], new_message=new_message)
        

    def forward_and_update_azure(self, new_message):

        content_variables_and_users_list = Chatbot.send_mc_message(self)
        Chatbot.forward_template_msg(content_variables_and_users_list, self, os.environ.get("MC_NOTIFY_SID"), new_message)
            
        # upload to azure
        try:
            manager.upload_data(self)
            return None # nothing to reply, maybe acknowledgement TODO
        except AzureSyncError as e:
            print(e.message)
            raise ReplyError(errors['AZURE_SYNC_ERROR'], intent=intents['TAKE_MC'], new_message=new_message)

    def cancel_mc_base():
        return