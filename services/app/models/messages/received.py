from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc, union_all
from typing import List
import uuid
from constants import intents, messages, CONFIRM, CANCEL, OK, PENDING_CALLBACK
import re
from dateutil.relativedelta import relativedelta
import os
import json
from config import client
from models.exceptions import ReplyError
from .abstract import Message
from .sent import MessageSent

from logs.config import setup_logger

class MessageReceived(Message):

    logger = setup_logger('models.message_received')

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    reply_sid = db.Column(db.String(80), nullable=True)

    __tablename__ = "message_received"

    # job = db.relationship('Job', backref='received_messages')

    __mapper_args__ = {
        "polymorphic_identity": "message_received"
    }

    def __init__(self, job_no, sid, body, seq_no=None):
        super().__init__(job_no, sid, body, seq_no) # initialise message

    @staticmethod
    def check_for_intent(message):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

        # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
        
        print(f"message: {message}")

        mc_pattern = r'(leave|mc|appointment|sick|doctor)' # TODO duplicate in dates.py
        mc_keyword_patterns = re.compile(mc_pattern, re.IGNORECASE)
        mc_match = mc_keyword_patterns.search(message)

        if mc_match:
            return intents['TAKE_MC']
        
        else:
            return intents['ES_SEARCH']
    
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


    def commit_reply_sid(self, sid):
        '''tries to update generated reply'''
        self.reply_sid = sid
        # db.session.add(self)
        db.session.commit()
        self.logger.info(f"reply committed with sid {self.reply_sid}")

        return True

    # def commit_reply(self, body):
    #     self.reply = body
    #     db.session.commit()

    #     self.logger.info(f"reply message committed with {self.reply}")
    
    # @classmethod
    # def get_reply_sid(cls, sid):
    #     '''This method gets the message instance based on the reply sid'''
    #     msg = cls.query.filter_by(
    #         reply_sid=sid
    #     ).first()
    #     return msg if msg else None


    ########################
    # CHATBOT FUNCTIONALITY
    ########################

    def create_reply_msg(self, reply, to_no=None):

        job = self.job

        self.logger.info(f"message status: {self.status}, job status: {job.status}")

        sent_msg = MessageSent.send_msg(reply, job, to_no)

        self.commit_reply_sid(sent_msg.sid)
        self.commit_status(OK)

class MessageConfirm(MessageReceived):

    logger = setup_logger('models.message_confirm')

    __tablename__ = "message_confirm"
    sid = db.Column(db.ForeignKey("message_received.sid"), primary_key=True)

    #for comparison with the latest confirm message. sid is of the prev message, not the next reply
    ref_msg_sid = db.Column(db.String(80), nullable=False)
    decision = db.Column(db.Integer, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "message_confirm",
        'inherit_condition': sid == MessageReceived.sid
    }

    def __init__(self, sid, body, ref_msg_sid, decision):

        ref_msg = MessageSent.get_message_by_sid(ref_msg_sid)
        job_no = ref_msg.job.job_no
        super().__init__(job_no, sid, body) # initialise message
        self.ref_msg_sid = ref_msg_sid
        self.decision = decision
        
    @classmethod
    def get_latest_confirm_message(cls, job_no):
        latest_message = cls.query \
                        .filter(cls.job_no == job_no) \
                        .order_by(cls.timestamp.desc()) \
                        .first()

        return latest_message if latest_message else None