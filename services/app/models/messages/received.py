from datetime import datetime, timedelta, date
from extensions import db, get_session
# from sqlalchemy.orm import 
from sqlalchemy import desc, union_all
from typing import List
from constants import intents, messages, OK
import re
from dateutil.relativedelta import relativedelta
import os
import json
from config import twilio_client
from models.exceptions import ReplyError
from .abstract import Message
from .sent import MessageSent
from constants import leave_keywords, leave_alt_words, leave_types
import logging

from logs.config import setup_logger

class MessageReceived(Message):

    logger = setup_logger('models.message_received')

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    reply_sid = db.Column(db.String(80), nullable=True)

    __tablename__ = "message_received"

    __mapper_args__ = {
        "polymorphic_identity": "message_received"
    }

    def __init__(self, job_no, sid, body, seq_no=None):
        super().__init__(job_no, sid, body, seq_no) # initialise message

    @staticmethod
    def check_for_intent(message):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''
        
        logging.info(f"message: {message}")
                
        leave_alt_words_pattern = re.compile(leave_alt_words, re.IGNORECASE)
        if leave_alt_words_pattern.search(message):
            return intents['TAKE_LEAVE']
            
        return intents['ES_SEARCH']
    
    @staticmethod
    def get_message(request):
        if "ListTitle" in request.form:
            message = request.form.get('ListTitle')
        else:
            message = request.form.get("Body")
        logging.info(f"Received {message}")
        return message
    
    @staticmethod
    def get_sid(request):
        sid = request.form.get("MessageSid")
        return sid

    def commit_reply_sid(self, sid):
        session = get_session()
        self.reply_sid = sid
        session.commit()
        self.logger.info(f"reply committed with sid {self.reply_sid}")

        return True


    ########################
    # CHATBOT FUNCTIONALITY
    ########################

    def create_reply_msg(self):

        '''Attributes to be set: self.reply'''

        job = self.job

        self.logger.info(f"message status: {self.status}, job status: {job.status}")

        sent_msg = MessageSent.send_msg(messages['SENT'], self.reply, job)

        self.commit_reply_sid(sent_msg.sid)
        # self.commit_status(OK)

        return sent_msg

class MessageConfirm(MessageReceived):

    logger = setup_logger('models.message_confirm')

    __tablename__ = "message_confirm"
    sid = db.Column(db.ForeignKey("message_received.sid"), primary_key=True)

    #for comparison with the latest confirm message. sid is of the prev message, not the next reply
    ref_msg_sid = db.Column(db.String(80), nullable=False)
    _decision = db.Column(db.Integer, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "message_confirm",
        'inherit_condition': sid == MessageReceived.sid
    }

    def __init__(self, job_no, sid, body, ref_msg_sid, decision):
        super().__init__(job_no, sid, body) # initialise message
        self.ref_msg_sid = ref_msg_sid
        self.decision = decision

    @property
    def decision(self):
        return str(self._decision) if self._decision else None
    
    @decision.setter
    def decision(self, value):
        self._decision = int(value)
        
    @classmethod
    def get_latest_sent_message(cls, job_no):
        session = get_session()
        latest_message = session.query(MessageSent) \
                        .filter(
                            MessageSent.job_no == job_no,
                            MessageSent.is_expecting_reply == True
                        ).order_by(cls.timestamp.desc()) \
                        .first()

        return latest_message if latest_message else None
    
    def check_for_other_decision(self):
        
        # other_decision = CANCEL if self.decision == CONFIRM else CANCEL
        session = get_session()

        other_message = session.query(MessageConfirm) \
                        .filter(
                            MessageConfirm.ref_msg_sid == self.ref_msg_sid,
                            MessageConfirm.sid != self.sid,
                            # MessageConfirm.decision == other_decision
                        ).first()
        
        # TODO not sure why other_decision doesnt work
        
        return other_message