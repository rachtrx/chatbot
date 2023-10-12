from datetime import datetime, timedelta
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import desc
from typing import List
import uuid
from constants import month_mapping
import re
from dateutil.relativedelta import relativedelta
from twilio.rest import Client

from constants import TEMP

intents = {
    "TAKE_MC": 1,
    "OTHERS": 2
}



def join_with_commas_and(lst):
    if not lst:
        return ""
    if len(lst) == 1:
        return lst[0]
    return ", ".join(lst[:-1]) + " and " + lst[-1]

def loop_relations(func):
    '''This wrapper wraps any function that takes in a user and loops over their relations.
    
    Returns a list of each relation function call result if there are relations, returns None if no relations.
    
    The function being decorated has a must have relation as the first param such that it can use the relation, but when calling it, it will take in the user'''
    
    def wrapper(user, *args, **kwargs):

        relations = user.get_relations()

        if all(relation is None for relation in relations):
            return None
        
        result = []

        for relation in relations:
            if relation is None:
                continue

            result.append(func(relation, *args, **kwargs))
        return result
    return wrapper

class User(db.Model):

    __tablename__ = "user"
    name: Mapped[str] = mapped_column(db.String(80), primary_key=True, nullable=False)
    number: Mapped[int] = mapped_column(db.Integer(), unique=True, nullable=False)
    messages = db.relationship('Message', backref=db.backref('user'), post_update=True)

    email: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)

    # Self-referential relationships
    reporting_officer_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    reporting_officer = db.relationship('User', backref=db.backref('subordinates'), remote_side=[name], post_update=True, foreign_keys=[reporting_officer_name])
    
    hod_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    hod = db.relationship('User', backref=db.backref('dept_members'), remote_side=[name], post_update=True, foreign_keys=[hod_name])

    def __init__(self, name, number, email, reporting_officer=None, hod=None):
        self.name = name
        self.number = number
        self.email = email
        self.reporting_officer = reporting_officer
        self.hod = hod

    @classmethod
    def get_user(cls, from_number):
        user = cls.query.filter_by(number=from_number).first()
        if user:
            return user
        else:
            return None
        
    def get_ro(self):
        return self.reporting_officer if self.reporting_officer else None
    
    def get_hod(self):
        return self.hod if self.hod else None
        
    def get_relations(self):
        return (self.get_ro(), self.get_hod())


    

# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class Message(db.Model):

    __tablename__ = "message"
    id: Mapped[str] = mapped_column(db.String(50), primary_key=True, nullable=False)
    name: Mapped[int] = mapped_column(db.Integer(), db.ForeignKey('user.name', ondelete="CASCADE"), nullable=False)
    type: Mapped[str]
    body: Mapped[str] = mapped_column(db.String(20), nullable=False)
    intent: Mapped[str] = mapped_column(db.String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "message",
        "polymorphic_on": "type",
    }

    def __init__(self, id, name, body, intent, timestamp):
        self.id = id
        self.name = name
        self.body = body
        self.intent = intent
        self.timestamp = timestamp

    @staticmethod
    def check_for_intent(user_str):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

        # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
        
        absent_keyword_patterns = re.compile(r'\b(?:leave|mc|sick|doctor)\b', re.IGNORECASE)
        match = absent_keyword_patterns.search(user_str)

        if match:
            return True
    
    @staticmethod
    def check_response(message):
        confirmation_pattern = re.compile(r'^(yes|no)$', re.IGNORECASE)
        
        if confirmation_pattern.match(message):
            return True
        return False
    
    @staticmethod
    def get_message(request):
        message = request.form.get("Body")
        print(f"Received {message}")
        return message
    
    @staticmethod
    def get_number(request):
        from_number = int(request.form.get("From")[-8:])
        return from_number
    
    # @classmethod
    # def add(cls, message,):


#IMPT SECTION possible to create an interface for time?

class McDetails(Message):

    #TODO other statuses eg. wrong duration

    __tablename__ = "mc_details"
    id: Mapped[int] = mapped_column(db.ForeignKey("message.id"), primary_key=True)
    start_date: Mapped[str] = mapped_column(db.String(20), nullable=True)
    end_date: Mapped[str] = mapped_column(db.String(20), nullable=True)
    duration: Mapped[str] = mapped_column(db.Integer, nullable=True)
    status: Mapped[int] = mapped_column(db.Integer(), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "mc_details"
    }

    def __init__(self, number, body, intent=intents['TAKE_MC'], status = TEMP):
        id=uuid.uuid4().hex
        name = User.get_user(number).name
        timestamp=(datetime.now())
        super().__init__(id, name, body, intent, timestamp)
        self.status = status
        db.session.add(self)
        db.session.commit()

    def commit_message(self, status):
        '''tries to update status otherise adds the object'''
        self.status = status

        db.session.add(self)
        db.session.commit()

        return True
    
    # TODO SHOULD THIS BE HERE OR MESSAGE CLASS
    @classmethod
    def get_recent_message(cls, number, status):
        '''Returns the user if they have any pending MC message from the user within 1 hour'''
        recent_msg = cls.query.filter_by(
            name=User.get_user(number).name, 
            status=status, 
            intent=intents["TAKE_MC"]
        ).order_by(
            desc(cls.timestamp)
        ).first()

        
        if recent_msg:
            timestamp = recent_msg.timestamp
            current_time = datetime.now()
            time_difference = current_time - timestamp
            print(time_difference)
            if time_difference < timedelta(hours=1):
                return recent_msg
            
        return False
    
    def generate_base(self):
        '''Generates the basic details of the MC, including the start, end and duration of MC'''
        duration_e = self.duration_extraction()
        dates = self.get_start_end_date()
        # if there are specified dates
        if dates:
            try: # for named month format
                self.duration_calc() # sets self.start_date, self.end_date, self.duration
                print(self.start_date, self.end_date)
            except: # for digit month format
                try:
                    self.duration_calc("%d %m %Y") # sets self.start_date, self.end_date, self.duration
                    print(self.start_date, self.end_date)
                except:
                    return False 
            # durations not equal where duration was specified
            if duration_e and duration_e != self.duration:
                raise DurationMismatchError(f"The durations do not match! Did you mean {self.duration} days?")
            
        else: # start and end dates not specified
            try: # duration specified
                self.duration = duration_e
                self.calc_start_end_date(self.duration) # sets self.start_date, self.end_date
                print(self.start_date, self.end_date)
            except: # start, end dates and duration not specifies
                return False
        
        return True


    def extract_start_end_date(self, match_obj):
        self.start_date = f'{match_obj.group("start_date")} {match_obj.group("start_month")} {datetime.now().year}'
        self.end_date = f'{match_obj.group("end_date")} {match_obj.group("end_month")} {datetime.now().year}'

        print(f'start date: {self.start_date}, end date: {self.end_date}')
    
    def get_start_end_date(self):
        '''This function takes in a mc_message and returns a tuple (start_date, end_date)'''
        return self.named_month_extraction() or self.named_ddmm_extraction() # sets self.start_date and self.end_date

    #SECTION Check for normal date pattern ie. 11/11 or somethijng
    def named_ddmm_extraction(self):

        date_pattern = r'0?[1-9]|[12][0-9]|3[01]'
        month_pattern = r'0?[1-9]|1[0-2]'

        start_pattern = r'\b(?P<start_date>' + date_pattern + r')/(?P<start_month>' + month_pattern + r')\b'
        end_pattern = r'\b(?P<end_date>' + date_pattern + r')/(?P<end_month>' + month_pattern + r')\b'

        normal_date_pattern = r'\b' + start_pattern + r'\s' + r'(?P<join>to|until)'+ r'\s' + end_pattern + r'\b'

        compiled_normal_date_pattern = re.compile(normal_date_pattern, re.IGNORECASE)

        match_dates = compiled_normal_date_pattern.search(self.body)

        try:
            if match_dates:
                print('matched 3rd')
                return self.extract_start_end_date(match_dates)
        except:
            return False

    # TODO CAN MOVE? VERY GENERIC
    @staticmethod
    def replace_with_full_month(match):
        '''pass in the match object from the sub callback and return the extended month string'''
        # Get the matched abbreviation or full month name
        month_key = match.group(0).lower()
        # Return the capitalized full month name from the dictionary
        return month_mapping[month_key]

    def named_month_extraction(self):
        user_str = re.sub(r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b', self.replace_with_full_month, self.body, flags=re.IGNORECASE)

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
        try:
            if match_dates: # case 1 January to 2 January
                print('matched first')
                return self.extract_start_end_date(match_dates)
            else:
                
                match_dates = compiled_month_first_pattern.search(user_str)
                if match_dates: # case January 1 to January 2
                    print('matched second')
                    return self.extract_start_end_date(match_dates)
        except:
            return False

    # SECTION Proper duration and general format
    def duration_extraction(self):
        duration_pattern = r'(?P<duration1>\d\d?\d?|a)'
        alternative_duration_pattern = r'(?P<duration2>\d\d?\d?|a)'
        day_pattern = r'(day|days)'
        action_pattern = r'(leave|mc|appointment)'

        # Combine the basic patterns into two main alternatives
        alternative1 = r'.*?' + duration_pattern + r' ' + day_pattern + r' .*?' + action_pattern
        alternative2 = r'.*?' + action_pattern + r' .*?' + alternative_duration_pattern + r' ' + day_pattern

        # Combine the two main alternatives into the final pattern
        urgent_absent_pattern = re.compile(r'\b(?:on|taking|take) (' + alternative1 + r'|' + alternative2 + r')\b', re.IGNORECASE)

        match_duration = urgent_absent_pattern.search(self.body)
        if match_duration:
            duration = match_duration.group("duration1") or match_duration.group("duration2")
            print(f'duration: {duration}')
            return duration

        print(duration)
        return False

    def duration_calc(self, date_format = "%d %B %Y"):
        '''takes in tuple (start date, end date) and the date format and returns the start and end date as strings, and the duration between the 2 datetime objects. 
        if duration is negative, it adds 1 to the year. also need to +1 to duration since today is included as well'''

        formatted_start_date = datetime.strptime(self.start_date, date_format)
        formatted_end_date = datetime.strptime(self.end_date, date_format)

        duration = (formatted_end_date - formatted_start_date).days + 1
        if duration < 0:
            formatted_end_date += relativedelta(years=1)
            duration = (formatted_end_date - formatted_start_date).days + 1

        self.start_date = formatted_start_date.strftime('%d/%m/%Y')
        self.end_date = formatted_end_date.strftime('%d/%m/%Y')
        self.duration = duration

    def calc_start_end_date(self, duration):
        '''takes in extracted duration and returns the calculated start and end date. need to -1 since today is the 1st day. This function is only used if there are no dates. It does not check if dates are correct as the duration will be assumed to be wrong'''
        start_date = datetime.now().date()
        end_date = (start_date + timedelta(days=int(duration) - 1))
        self.start_date = start_date.strftime('%d/%m/%Y')
        self.end_date = end_date.strftime('%d/%m/%Y')

        return True
    
    def send_message(self, client=None):

        @loop_relations
        def generate_each_message(relation):
            '''This function sets up the details of the forward to HOD and reporting officer message'''
            
            body = f'Hi {relation.name}! This is to inform you that {self.user.name} will be taking {self.duration} days MC from {self.start_date} to {self.end_date}'

            if client:
                from_number = '+18155730824'  # Your Twilio number

                # Send the message
                message = client.messages.create(
                    to='+65' + str(relation.number),
                    from_=from_number,
                    body=body
                )

            else:
                return body

            return True
        
        messages_list = generate_each_message(self.user)
        print(f'Messages List: {messages_list}')
        return messages_list
    
    
    def generate_reply(self):
        '''This function gets a mc_details object and returns a confirmation message'''

        statement = f"Hi {self.user.name}, Kindly confirm that you are on MC for {self.duration} days from {self.start_date} to {self.end_date}. I will help you to inform "

        @loop_relations
        def generate_each_relation(relation):

            return f"{relation.name} ({str(relation.number)})"
        
        statements_list = generate_each_relation(self.user)

        if statements_list == None:
            return None

        # list of return statements
        else:
            statement = statement + join_with_commas_and(statements_list) + " (Yes/No)"
        
        return statement

    

class DurationMismatchError(Exception):
    """thows error if extracted duration and calculated duration are different"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)