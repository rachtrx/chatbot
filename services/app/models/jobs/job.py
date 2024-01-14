from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
import logging
from constants import intents, FAILED, PENDING, DELIVERED, OK
import re
from dateutil.relativedelta import relativedelta
import os
import uuid
from utilities import current_sg_time
from constants import intents, errors
from ..exceptions import ReplyError

from models.users import User
from models.messages import MessageConfirm
from models.messages.abstract import Message

from logs.config import setup_logger


# TODO CHANGE ALL MESSAGE TO USER_STR

class Job(db.Model):

    logger = setup_logger('models.job')

    __tablename__ = 'job'
    type = db.Column(db.String(50))
    job_no = db.Column(db.String, primary_key=True)

    name = db.Column(db.String(80), db.ForeignKey('users.name'), nullable=True)
    # Other job-specific fields
    status = db.Column(db.Integer(), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=current_sg_time())
    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User", backref="jobs")
    
    __mapper_args__ = {
        "polymorphic_identity": "job",
        "polymorphic_on": "type",
    }

    def __init__(self, name):
        print(f"current time: {current_sg_time()}")
        self.job_no = uuid.uuid4().hex
        self.name = name
        self.created_at = current_sg_time()
        self.status = PENDING
        self.is_expecting_user_reply=False # not db
        db.session.add(self)
        db.session.commit()

    @classmethod
    def create_job(cls, intent, *args, **kwargs):
        if intent == intents['TAKE_MC']:
            from .mc.job_mc import JobMc
            new_job = JobMc(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == intents['ES_SEARCH']:
            from .es.job_es import JobEs
            new_job =  JobEs(*args, **kwargs)
        elif intent == intents['OTHERS']:
            new_job =  cls(*args, **kwargs)
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        new_job.user.is_blocking = True
        return new_job
    
    def commit_status(self, status):
        '''tries to update status'''

        if status is None:
            return
        
        self.status = status
        # db.session.add(self)

        if status == OK or status == FAILED:
            self.user.is_blocking = False

        db.session.commit()

        self.logger.info(f"job status: {status}")

        return True
    
    def commit_cancel(self):
        '''tries to cancel'''
        self.is_cancelled = True
        db.session.commit()

        return True
    
    def all_messages_replied(self):
        all_msgs = self.messages

        # msges = "\n".join([f"{msg.type + msg.body}" if msg.body else "PENDING" for msg in all_msgs])

        # self.logger.info("MESSAGES:\n" + msges)
        
        if all(msg.status == OK for msg in all_msgs) and self.status != FAILED:
            return True
        return False
    
    @classmethod
    def get_recent_job(cls, number):
        '''Returns the user if they have any pending MC message from the user within 5mins'''
        latest_message = Message.query.join(cls).join(User).filter(
            User.name == User.get_user(number).name,
            Job.status != FAILED
            # dont need worry about forward message since its a message_sent object
        ).order_by(
            desc(Message.timestamp)
        ).first()
        
        if latest_message:
            last_timestamp = latest_message.timestamp
            current_time = current_sg_time()
            cls.logger.info(f"last timestamp: {last_timestamp}, current timestamp: {current_time}")
            time_difference = current_time - last_timestamp
            print(time_difference)
            if time_difference < timedelta(minutes=5):
                cls.logger.info(f"found job: {latest_message.body}")
                return latest_message.job
            
        return None

    def validate_confirm_message(self):
        pass

    def handle_user_reply_action(self):
        '''need to return the reply. if its a template, 1st argument is whether a user reply is mandatory, followed by sid and cv'''
        pass

    def check_for_complete(self):
        pass

    def entry_action(self):
        pass

    def handle_request(self):

        self.is_expecting_user_reply = False

        if isinstance(self.current_msg, MessageConfirm):
            # these 2 functions are implemented with method overriding
            self.validate_confirm_message() # checks for ReplyErrors based on state
            reply = self.handle_user_reply_action()

        # first message
        elif self.current_msg.seq_no == 1:
            reply = self.entry_action()
            
        else:
            logging.info(f"seq no: {self.current_msg.seq_no}, decision: {self.current_msg.decision}")
            raise ReplyError(errors['UNKNOWN ERROR'])

        self.current_msg.create_reply_msg(reply)

class JobUnknown(Job):

    logger = setup_logger('models.job')

    __tablename__ = 'job_unknown'
    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    from_no = db.Column(db.Integer(), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_unknown",
    }

    def __init__(self, from_no):
        super().__init__(name=None)
        self.from_no = from_no