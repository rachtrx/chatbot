from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc, union_all
from typing import List
import uuid
from constants import intents, messages, OK
import re
from dateutil.relativedelta import relativedelta
import os
import json
from config import client
from models.exceptions import ReplyError
from .abstract import Message
from .sent import MessageSent
from constants import mc_keywords, mc_alt_words, leave_types
from utilities import run_new_context, get_session

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
        
        print(f"message: {message}")

        mc_keyword_patterns = re.compile(mc_keywords, re.IGNORECASE)
        mc_match = mc_keyword_patterns.search(message)

        if mc_match:
            matched_term = mc_match.group(0) if mc_match else None
            leave_type = None
            for key, values in leave_types.items():
                if matched_term.lower() in [v.lower() for v in values]:
                    leave_type = key
                    return intents['TAKE_MC'], leave_type
            # UNKNOWN ERROR... keyword found but couldnt lookup 
            return None, None
                
        mc_altword_patterns = re.compile(mc_alt_words, re.IGNORECASE)
        if mc_altword_patterns.search(message):
            return intents['TAKE_MC_NO_TYPE'], None
            
        
        return intents['ES_SEARCH'], None
    
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
        session = get_session()
        self.reply_sid = sid
        session.commit()
        self.logger.info(f"reply committed with sid {self.reply_sid}")

        return True


    ########################
    # CHATBOT FUNCTIONALITY
    ########################

    def create_reply_msg(self, reply):

        job = self.job

        self.logger.info(f"message status: {self.status}, job status: {job.status}")

        sent_msg = MessageSent.send_msg(messages['SENT'], reply, job)

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
        latest_message = MessageSent.query \
                        .filter(
                            MessageSent.job_no == job_no,
                            MessageSent.is_expecting_reply == True
                        ).order_by(cls.timestamp.desc()) \
                        .first()

        return latest_message if latest_message else None
    
    def check_for_other_decision(self):
        
        # other_decision = CANCEL if self.decision == CONFIRM else CANCEL

        other_message = MessageConfirm.query \
                        .filter(
                            MessageConfirm.ref_msg_sid == self.ref_msg_sid,
                            MessageConfirm.sid != self.sid,
                            # MessageConfirm.decision == other_decision
                        ).first()
        
        # TODO not sure why other_decision doesnt work
        
        return other_message