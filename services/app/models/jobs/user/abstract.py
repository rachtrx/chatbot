from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import uuid
import logging
from constants import intents, PENDING, OK, CONFIRM, CANCEL
import re
from dateutil.relativedelta import relativedelta
import os
import uuid
from utilities import current_sg_time, run_new_context, get_session
from constants import intents, errors
from models.exceptions import ReplyError
from models.jobs.abstract import Job
from models.messages.abstract import Message

from models.users import User

from logs.config import setup_logger

class JobUser(Job): # Abstract class

    logger = setup_logger('models.job_user')

    __tablename__ = 'job_user'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    
    name = db.Column(db.String(80), nullable=True) # dont create relationship otherwise the name is gone after deleted
    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_user",
        "polymorphic_on": "type"
    }

    @property
    def user(self):
        session = get_session()
        user = session.query(User).filter_by(name=self.name).first()
        return user

    def __init__(self, name):
        super().__init__()
        self.name = name

    @classmethod
    def create_job(cls, intent, *args, **kwargs):
        '''args is typically "user" and "options"'''
        if intent == intents['TAKE_MC']:
            from .mc import JobMc
            new_job = JobMc(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == intents['ES_SEARCH']:
            from .es import JobEs
            new_job =  JobEs(*args, **kwargs)
        elif intent == intents['OTHERS']:
            new_job =  cls(*args, **kwargs)
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        if new_job.user:
            new_job.user.is_blocking = True
            cls.logger.info("blocking user")
        session = get_session()
        session.add(new_job)
        session.commit()
        return new_job
    
    def commit_cancel(self):
        '''tries to cancel'''
        session = get_session()
        self.status = PENDING
        self.is_cancelled = True
        session.commit()

        self.reset_complete_conditions() # TO IMPLEMENT
        return True
    
    @classmethod
    def get_recent_pending_job(cls, number):
        '''Returns the user if they have any pending MC message from the user within 5mins'''
        session = get_session()
        latest_message = session.query(Message).join(cls).join(User, cls.name == User.name).filter(
            User.name == User.get_user(number).name,
            cls.status.between(300, 399)
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
            if time_difference < timedelta(minutes=1):
                cls.logger.info(f"message found: {latest_message.body}")
                return latest_message.job
            
        return None

    def validate_confirm_message(self):
        pass

    def handle_user_reply_action(self):
        '''need to return the reply. if its a template, 1st argument is whether a user reply is mandatory, followed by sid and cv'''
        pass

    def entry_action(self):
        pass

    def run_background_tasks(self):
        pass

    def handle_request(self):

        logging.info("job set with expects")

        from models.messages.received import MessageConfirm

        if isinstance(self.current_msg, MessageConfirm):
            # these 2 functions are implemented with method overriding
            decision = self.current_msg.decision
            if decision != CONFIRM and decision != CANCEL:
                logging.error(f"UNCAUGHT DECISION {decision}")
                raise ReplyError(errors['UNKNOWN_ERROR'])
            self.validate_confirm_message() # checks for ReplyErrors based on state
            self.commit_status(PENDING)
            reply = self.handle_user_reply_action()

        # first message
        elif self.current_msg.seq_no == 1:
            reply = self.entry_action()
            
        else:
            logging.info(f"seq no: {self.current_msg.seq_no}, decision: {self.current_msg.decision}")
            raise ReplyError(errors['UNKNOWN ERROR'])

        self.current_msg.create_reply_msg(reply)

        if self.current_msg.seq_no == 1:
            return
        
        self.run_background_tasks() # to improve
        