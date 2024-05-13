from datetime import datetime, timedelta, date
from twilio.base.exceptions import TwilioRestException
from extensions import db, get_session
# from sqlalchemy.orm import 
from sqlalchemy import desc
from typing import List
import logging
from constants import errors, Decision, JobStatus, SelectionType, Intent, MessageType, AuthorizedDecision
import re
# from dateutil.relativedelta import relativedelta
from utilities import current_sg_time, log_instances
from models.exceptions import ReplyError
from models.jobs.abstract import Job
from models.jobs.unknown.unknown import JobUnknown
from models.messages.abstract import Message
from models.messages.sent import MessageSent

from models.messages.received import MessageReceived, MessageSelection
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
        if intent == Intent.TAKE_LEAVE:
            from .leave import JobLeave
            new_job = JobLeave(*args, **kwargs)
        elif intent == Intent.CANCEL_LEAVE:
            from .leave import JobLeaveCancel
            new_job = JobLeaveCancel(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == Intent.ES_SEARCH:
            from .es import JobEs
            new_job =  JobEs(*args, **kwargs)
        elif intent == Intent.OTHERS:
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

    def validate_selection_message(self, selection):
        pass

    def handle_user_reply_action(self):
        '''need to return the reply. if its a template, 1st argument is whether a user reply is mandatory, followed by sid and cv'''
        pass

    def handle_user_entry_action(self):
        pass

    def is_partially_completed(self):
        return False
    
    @classmethod
    def create_new_job(cls, user_str, name):
        intent = MessageReceived.check_for_intent(user_str)
        if intent == Intent.ES_SEARCH or intent == None:
            raise ReplyError(errors['ES_REPLY_ERROR'])

        job = cls.create_job(intent, user_str, name)
        return job

    @classmethod
    def general_workflow(cls, job_information):
        from models.messages.sent import MessageSent
        job = user = received_msg = selection = None

        logging.info(f"Job information passed to general workflow from app.py and redis: {job_information}")
        sid = job_information['sid']
        user_str = job_information['user_str']
        raw_from_no = job_information['from_no']

        try:
            try:
                user = User.get_user(raw_from_no)
                if not user:
                    raise ReplyError(errors['USER_NOT_FOUND'])
                
                # SECTION NEW JOB
                if not job_information.get('replied_msg_sid', None):
                    job = cls.create_new_job(user_str, user.name)
                    received_msg = Message.create_message(MessageType.RECEIVED, job.job_no, sid, user_str)
                    
                else: # selection message
                    sent_sid = job_information.get("sent_sid", None)
                    selection_type = job_information.get("selection_type", None)

                    rawSelection = job_information.get("selection", None) # numeric val
                    if not rawSelection:
                        raise ReplyError(errors['UNKNOWN_ERROR']) # IMPT SELECTION BUT NO SELECTION_TYPE IS A LATE MSG

                    replied_msg_sid = job_information.get('replied_msg_sid', None) # IMPT need to compare with sent_sid

                    ref_msg = MessageSent.get_message_by_sid(replied_msg_sid) # try to check the database
                    if not ref_msg:
                        raise ReplyError(errors['SENT_MESSAGE_MISSING']) # no ref msg
                    
                    if not selection_type: # LATE MSG
                        selection_type = ref_msg.selection_type
                        if not selection_type:
                            raise ReplyError(errors['UNKNOWN_ERROR'])

                    selection = selection_type.value[int(rawSelection)]
                
                    job = ref_msg.job # retrieve the job instance from ORM database

                    if job.user.number != user.number and job.status == JobStatus.PENDING_AUTHORISED_DECISION and job.user.reporting_officer == user.reporting_officer:
                        # IMPT is a authorised user!
                        pass

                    # SECTION By now, all messages HAVE selection.
                    # IMPT First handle msges whose cache has been cleared → missing sent_sid → valid only if cancelling/approving/rejecting, which are all DECISIONS. They MUST BE CLEARED in order to unblock the user.
                    if not sent_sid:
                        if (selection == Decision.CONFIRM or selection == Decision.CANCEL) and job.status == JobStatus.PENDING_DECISION:
                            raise ReplyError(job.timeout_msg)
                        elif selection == Decision.CANCEL:
                            if job.status == JobStatus.PENDING_AUTHORISED_DECISION:
                                # inform RO of cancellation
                                # remove from database
                                pass
                            elif job.status == JobStatus.REJECTED:
                                # throw error that cannot cancel when rejected
                                pass
                            elif job.is_partially_completed():
                                job.commit_cancel()
                                job = job.create_cancel_job(user_str)
                        elif selection == Decision.APPROVE and job.status == JobStatus.PENDING_AUTHORISED_DECISION:
                            job.approve()
                        elif selection == Decision.REJECT and job.status == JobStatus.PENDING_AUTHORISED_DECISION:
                            job.reject()
                        else:
                            raise ReplyError(errors['JOB_COMPLETED']) # likely because job is completed / failed / waiting for completion already

                    elif sent_sid != replied_msg_sid:
                        if job.status == JobStatus.PENDING_DECISION:
                            latest_sent_msg = MessageSelection.get_latest_sent_message(job.job_no) # probably not needed
                            if sent_sid != latest_sent_msg.sid:
                                raise ReplyError(job.not_replying_to_last_msg) # TODO CAN CONSIDDER USER RETRYING
                            else:
                                raise ReplyError(errors['UNKNOWN_ERROR']) # shouldnt happen but...
                        else:
                            raise ReplyError(errors['JOB_LEAVE_FAILED']) # TODO really?
                    
                    else: # IMPT by now, sent_sid == replied_msg_sid. only can allow for confirm, cancel, or listitem
                        if job.status != JobStatus.PENDING_DECISION:
                            raise ReplyError(errors['UNKNOWN_ERROR'])
                        job.commit_status(JobStatus.PROCESSING)

                        if selection == Decision.CANCEL:
                            raise ReplyError(job.cancel_msg, job_status=JobStatus.CLIENT_ERROR)
                        if selection == Decision.CONFIRM:
                            job.update_info(job_information)
                        elif selection == AuthorizedDecision.APPROVE or selection == AuthorizedDecision.REJECT:
                            raise ReplyError(errors['UNKNOWN_ERROR'])
                        else: # IMPT choice found
                            job.update_info(job_information, selection_type, selection) # TODO # IMPT SEE constants.py SelectionType ... IMPT
                            logging.info(f"UPDATED INFO")
                    
                    # CHECK if there was a cancel. # IMPT bypass_validation is currently ensuring that the user doesnt cancel when clicking on a list item
                    received_msg = Message.create_message(MessageType.CONFIRM, job.job_no, sid, user_str, replied_msg_sid, selection)
                            
                job.background_tasks = []
                job.user_str = user_str
                job.sent_msg = job.create_reply_msg(job.handle_request(selection), received_msg) # TODO check if need job = job.handle_request()
                
                if getattr(job, "forwards_seq_no", None):
                    logging.info("FORWARDS SEQ NO FOUND")
                    job.background_tasks.append([job.check_message_forwarded, (job.forwards_seq_no, job.map_job_type(), True)])
                    job.run_background_tasks()
                else:
                    logging.error("FORWARDS SEQ NO NOT FOUND")
                    
            except TwilioRestException:
                raise ReplyError("Unable to create record: Twilio API failed. Please try again")

                logging.info(f"In General Workflow {job.status}, {job.sent_msg.sid}")

            except ReplyError as re: # problem

                if not job:
                    if user:
                        name = user.name
                        job = JobUser.create_job(re.intent, user_str, name)
                    else:
                        logging.info(f"unknown number: {raw_from_no}")
                        prev_job = JobUnknown.check_for_prev_job(raw_from_no)
                        if prev_job:
                            logging.info("doing nothing")
                            return
                        job = JobUnknown(raw_from_no)
                    job.commit_status(re.job_status)
                if not received_msg:
                    received_msg = Message.create_message(MessageType.RECEIVED, job.job_no, sid, user_str)

                job.sent_msg = job.create_reply_msg(re.err_message, received_msg)

            if job and job.status == JobStatus.PROCESSING: # may throw error due to leave_type empty but still processing
                return job.set_cache_data()
            return None
   
        except Exception:
            logging.error("Something wrong with application code")
            logging.error(traceback.format_exc())
            if job and not getattr(job, "local_db_updated", None) and not job.status == OK:
                job.commit_status(JobStatus.SERVER_ERROR)
            raise

    ########################
    # CHATBOT FUNCTIONALITY
    ########################

    def create_reply_msg(self, reply, received_msg):
        '''abstract function to create a reply message'''

        sent_msg = MessageSent.send_msg(MessageType.SENT, reply, self)

        received_msg.commit_reply_sid(sent_msg.sid)
        # self.commit_status(OK)

        return sent_msg
    
    @overrides
    def validate_complete(self):
        pass

    def set_cache_data(self):
        pass