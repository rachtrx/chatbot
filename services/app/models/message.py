from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, month_mapping, day_mapping, TEMP, days_arr, DOUBLE_MESSAGE, mc_pattern
import re
from dateutil.relativedelta import relativedelta
import os
from utilities import current_sg_time


# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class Message(db.Model):

    __tablename__ = "message"
    sid = db.Column(db.String(80), primary_key=True, nullable=False)
    type = db.Column(db.String(50))
    body = db.Column(db.String(), nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.Integer(), nullable=False)
    seq_no = db.Column(db.Integer(), nullable=False)
    reply = db.Column(db.String(), nullable=True)
    reply_sid = db.Column(db.String(80), nullable=True)
    # latest_sid = db.Column(db.String(80), nullable=True)

    job_number = db.Column(db.String, db.ForeignKey('job.job_number'), nullable=True)
    job = db.relationship('Job', backref='messages')

    __mapper_args__ = {
        "polymorphic_identity": "message",
        "polymorphic_on": "type",
    }

    def __init__(self, job_number, sid, body):
        print(f"current time: {current_sg_time()}")
        self.job_number = job_number
        self.sid = sid
        self.body = body
        self.timestamp = current_sg_time()
        self.status = TEMP
        self.seq_no = self.get_seq_no(job_number) + 1 if self.get_seq_no(job_number) is not None else 1
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_seq_no(cls, job_number):
        return db.session.query(db.func.max(cls.seq_no)).filter(cls.job_number == job_number).scalar()

    @staticmethod
    def check_for_intent(message):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

        # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
        
        print(f"message: {message}")
        mc_keyword_patterns = re.compile(mc_pattern, re.IGNORECASE)
        mc_match = mc_keyword_patterns.search(message)

        if mc_match:
            return intents['TAKE_MC']
        
        else:
            return intents['ES_SEARCH']
    
    # @staticmethod
    # def check_confirm_cancel(message):
    #     confirmation_pattern = re.compile(r'^(confirm|cancel)$', re.IGNORECASE)
        
    #     if confirmation_pattern.match(message):
    #         return True
    #     return False
    
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

    
    def commit_status(self, status):
        '''tries to update status'''
        self.status = status
        # db.session.add(self)
        db.session.commit()

        return True

    def commit_reply_sid(self, msg_meta):
        '''tries to update generated reply'''
        self.reply_sid = msg_meta.sid
        # db.session.add(self)
        db.session.commit()

        return True

    def commit_reply(self, body):
        self.reply = body
        db.session.commit()

    @classmethod
    def get_message_by_sid(cls, sid):
        msg = cls.query.filter_by(
            sid=sid
        ).first()
        return msg
    
    @classmethod
    def get_reply_sid(cls, sid):
        '''This method will be used when replying the user'''
        msg = cls.query.filter_by(
            reply_sid=sid
        ).first()
        return msg