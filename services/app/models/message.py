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

from .user import User

# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class Message(db.Model):

    __tablename__ = "message"
    sid = db.Column(db.String(80), primary_key=True, nullable=False)
    name = db.Column(db.Integer(), db.ForeignKey('user.name', ondelete="CASCADE"), nullable=False)
    type = db.Column(db.String(50))
    body = db.Column(db.Integer(), nullable=False)
    intent = db.Column(db.Integer(), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.Integer(), nullable=False)
    latest_sid = db.Column(db.String(80), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "message",
        "polymorphic_on": "type",
    }

    def __init__(self, sid, name, body, intent, status, timestamp):
        self.sid = sid
        self.name = name
        self.body = body
        self.intent = intent
        self.timestamp = timestamp
        self.status = status

    @staticmethod
    def check_for_intent(user_str):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

        # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
        
        print(f"user_str: {user_str}")
        mc_keyword_patterns = re.compile(r'\b(?:leave|mc|sick|doctor)\b', re.IGNORECASE)
        mc_match = mc_keyword_patterns.search(user_str)

        if mc_match:
            return True
    
    @staticmethod
    def check_yes_no(message):
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
    
    @staticmethod
    def get_sid(request):
        sid = request.form.get("MessageSid")
        return sid

    
    def commit_message(self, status):
        '''tries to update status otherise adds the object'''
        self.status = status
        db.session.add(self)
        db.session.commit()

        return True
    
    @classmethod
    def get_message_by_sid(cls, sid):
        msg = cls.query.filter_by(
            status=PENDING_CALLBACK,
            sid=sid
        ).first()
        return msg
    
    @classmethod
    def get_message_by_latest_sid(cls, sid):
        msg = cls.query.filter_by(
            status=PENDING_CALLBACK,
            latest_sid=sid
        ).first()
        return msg
    
    @classmethod
    def get_recent_message(cls, number):
        '''Returns the user if they have any pending MC message from the user within 1 hour'''
        recent_msg = cls.query.filter_by(
            name=User.get_user(number).name
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
            
        return None

    def notify_complete(self, client):
        client.messages.create(
                from_=os.environ.get('TWILIO_NO'),
                to= 'whatsapp:+65' + str(self.user.number),
                body=f"All messages have been sent successfully"
            )
        
    def update_latest_sid_for_callback(self, sid):
        self.latest_sid = sid
        self.commit_message(PENDING_CALLBACK)

    
    # @classmethod
    # def add(cls, message,):