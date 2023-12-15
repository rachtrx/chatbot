from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, month_mapping, day_mapping, TEMP, days_arr, FAILED, FORWARD_SENT, COMPLETE, FORWARD_FAILED
import re
from dateutil.relativedelta import relativedelta
import os

from .message import Message

class UnknownMessage(Message):

    __tablename__ = "unknown_message"
    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    from_name = db.Column(db.String(80), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "unknown_message",
        'inherit_condition': sid == Message.sid
    }

    def __init__(self, job_no, sid, body, from_name):
        self.from_name = from_name
        
        super().__init__(job_no, sid, body) # initialise message

class ForwardMessage(Message):

    #TODO other statuses eg. wrong duration

    __tablename__ = "forward_message"
    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    to_name = db.Column(db.String(80), nullable=True)
    forward_status = db.Column(db.Integer(), nullable=False)
    message_pending_forward = db.Column(db.ForeignKey("message.sid"))

    __mapper_args__ = {
        "polymorphic_identity": "forward_message",
        'inherit_condition': sid == Message.sid
    }

    def __init__(self, job_no, sid, body, to_name, message_pending_forward):
        self.to_name = to_name
        self.forward_status = TEMP
        self.message_pending_forward = message_pending_forward
        super().__init__(job_no, sid, body) # initialise message

    def get_other_forwards(self):
        msges = ForwardMessage.query.filter_by(
            message_pending_forward = self.message_pending_forward
        )
        return msges
    
    def commit_forward_message(self, body):
        self.body = body
        db.session.commit()

    def commit_forward_status(self, status):
        self.forward_status = status
        db.session.commit()

    def notify_status(self):

        if self.forward_status == FORWARD_FAILED:
            reply = f"Message to {self.to_name} was UNSUCCESSFUL"

        elif self.forward_status == FORWARD_SENT:
            reply = f"Message to {self.to_name} was successful"
                
        return reply
    
    def get_pending_forward_message(self):
        message_pending_forward = Message.query.filter_by(
            sid = self.message_pending_forward
        ).first()

        return message_pending_forward
    
    def acknowledge_decision(self):

        return "All messages have been sent successfully. Your current MC dates are: " #TODO