from datetime import datetime, timedelta, date

from twilio.base.exceptions import TwilioRestException

from extensions import db, get_session
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import logging
from constants import intents,messages, PENDING_USER_REPLY, OK, PROCESSING, DECISIONS, SERVER_ERROR, CLIENT_ERROR
import re
from dateutil.relativedelta import relativedelta
from utilities import current_sg_time, log_instances
from constants import intents, errors
from models.exceptions import ReplyError
from models.jobs.abstract import Job
from models.jobs.unknown.unknown import JobUnknown
from models.messages.abstract import Message

from models.messages.received import MessageReceived, MessageConfirm
import traceback

from models.users import User
from logs.config import setup_logger
from overrides import overrides
import time

class JobUser(Job): # Abstract class

    logger = setup_logger('models.job_user')
    max_pending_duration = timedelta(minutes=1)

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
        if not getattr(self, '_user', None):
            session = get_session()
            self.user = session.query(User).filter_by(name=self.name).first()

        return self._user
    
    @user.setter
    def user(self, value):
        self._user = value

    def __init__(self, name):
        super().__init__()
        self.name = name

    @classmethod
    def create_job(cls, intent, user_str, *args, **kwargs):
        '''args is typically "user" and "options"'''
        if intent == intents['TAKE_LEAVE']:
            from .leave import JobLeave
            new_job = JobLeave(*args, **kwargs)
        elif intent == intents['CANCEL_LEAVE']:
            from .leave import JobLeaveCancel
            new_job = JobLeaveCancel(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == intents['ES_SEARCH']:
            from .es import JobEs
            new_job =  JobEs(*args, **kwargs)
        elif intent == intents['OTHERS']:
            new_job =  cls(*args, **kwargs)
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        new_job.user_str = user_str
        session = get_session()
        session.add(new_job)
        session.commit()
        return new_job
    
    def commit_cancel(self):
        '''tries to cancel'''
        session = get_session()
        self.is_cancelled = True
        session.commit()

    def validate_confirm_message(self):
        pass

    def handle_user_reply_action(self):
        '''need to return the reply. if its a template, 1st argument is whether a user reply is mandatory, followed by sid and cv'''
        pass

    def handle_user_entry_action(self):
        pass

    def bypass_validation(self, decision):
        return False
    
    def is_cancel_job(self, decision):
        return False

    @classmethod
    def general_workflow(cls, job_information):
        job_completed_data = job = received_msg = user = None

        sid = job_information['sid']
        user_str = job_information['user_str']

        try:
            logging.info(f"Job information passed to general workflow {job_information}")
            raw_from_no = job_information['from_no']
            from_no = raw_from_no[-8:]
            user = User.get_user(from_no)
            if not user:
                raise ReplyError(errors['USER_NOT_FOUND'])

            if "choice" in job_information or "decision" in job_information:

                from models.messages.sent import MessageSent
                decision = job_information.get("decision", None)
                choice = job_information.get("choice", None)
                replied_msg_sid = job_information['replied_msg_sid']
                sent_sid = job_information.get("sent_sid", None)
                ref_msg = MessageSent.get_message_by_sid(replied_msg_sid) # try to check the database
                if not ref_msg:
                    raise ReplyError(errors['SENT_MESSAGE_MISSING']) # no ref msg

                job = ref_msg.job

                # CHECK if there was a decision. # IMPT bypass_validation is currently ensuring that the user doesnt cancel when clicking on a list item
                if decision and job.bypass_validation(decision) and job.is_cancel_job(decision): 
                    job.commit_cancel()
                    job = job.create_cancel_job(user_str)
                    received_msg = Message.create_message(messages['CONFIRM'], job.job_no, sid, user_str, replied_msg_sid, decision)

                else: # user replied with Confirm/Cancel
                    received_msg = Message.create_message(messages['CONFIRM'], job.job_no, sid, user_str, replied_msg_sid, decision or choice)
                    
                    if sent_sid == replied_msg_sid:
                        logging.info(f"STATUS IN VALIDATION: {job.status}")
                        if job.status != PENDING_USER_REPLY:
                            raise ReplyError(errors['UNKNOWN_ERROR'])
                        job.commit_status(PROCESSING)

                        if decision:
                            if decision == DECISIONS['CANCEL']:
                                raise ReplyError(job.cancel_msg, job_status=CLIENT_ERROR)
                            if decision == DECISIONS['CONFIRM']:
                                job.update_info(job_information)
                            else:
                                raise ReplyError(errors['UNKNOWN_ERROR'])
                        else: # IMPT choice found
                            job.update_info(job_information)
                            logging.info(f"UPDATED INFO! USER STR: {getattr(job, 'user_str', None)}")
                    
                    elif not sent_sid:
                        if job.status == PENDING_USER_REPLY: # no recent job in cache
                            raise ReplyError(job.timeout_msg)
                        elif job.status == CLIENT_ERROR and decision == DECISIONS['CONFIRM']:
                            raise ReplyError(job.confirm_after_cancel_msg)
                        elif job.status == CLIENT_ERROR and decision == DECISIONS['CANCEL']:
                            raise ReplyError(job.cancel_after_fail_msg)
                        else:
                            raise ReplyError(errors['JOB_COMPLETED']) # likely because job is completed / failed / waiting for completion already
                    
                    # recent messsage with job_no and sent_sid but they dont match
                    elif sent_sid != replied_msg_sid:
                        if job.status == PENDING_USER_REPLY:
                            latest_sent_msg = MessageConfirm.get_latest_sent_message(job.job_no)
                            if sent_sid and sent_sid != latest_sent_msg.sid:
                                raise ReplyError(job.not_replying_to_last_msg) # TODO CAN CONSIDDER USER RETRYING
                        else:
                            raise ReplyError(errors['JOB_LEAVE_FAILED'])
                        
                    else:
                        raise ReplyError(errors['UNKNOWN_ERROR'])
                        
            else:

                # NEW JOB WILL BE CREATED
                intent = MessageReceived.check_for_intent(user_str)
                if intent == intents['ES_SEARCH'] or intent == None:
                    raise ReplyError(errors['ES_REPLY_ERROR'])

                job = JobUser.create_job(intent, user_str, user.name)
                received_msg = Message.create_message(messages['RECEIVED'], job.job_no, sid, user_str)
                job.user_str = user_str # IMPT this will only be set here and after a user select from list message

            job.background_tasks = []

            job.received_msg = received_msg
            job.handle_request() # TODO check if need job = job.handle_request()
            try:
                
                job.sent_msg = job.received_msg.create_reply_msg()
                job_completed_data = job.get_cache_data()

                if getattr(job, "forwards_seq_no", None):
                    logging.info("FORWARDS SEQ NO FOUND")
                    job.background_tasks.append([job.check_message_forwarded, (job.forwards_seq_no, job.map_job_type(), True)])
                    job.run_background_tasks()
                else:
                    logging.info("FORWARDS SEQ NO NOT FOUND")
            except TwilioRestException:
                raise ReplyError("Unable to create record: Twilio API failed. Please try again")

            logging.info(f"In General Workflow {job.status}, {job.sent_msg.sid}")

        except ReplyError as re: # problem

            job_completed_data = None

            sent_msg = re.send_error_msg(sid, user_str, user if user else raw_from_no)

            if job and job.status == PROCESSING:
                job_completed_data = {
                    'job_no': job.job_no,
                    'status': job.status,
                    'initial_msg': user_str,
                    'sent_sid': sent_msg.sid
                }
                
                logging.info(f"IN REPLYERROR DATA: {job_completed_data}")
   
        except Exception:
            logging.error("non reply error exception")
            logging.error(traceback.format_exc())
            if job and not getattr(job, "local_db_updated", None) and not job.status == OK:
                job.commit_status(SERVER_ERROR)

        finally:
            return job_completed_data
    
    @overrides
    def validate_complete(self):
        pass

    def get_cache_data(self):
        pass