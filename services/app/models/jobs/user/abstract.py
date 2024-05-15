import logging
import traceback

from sqlalchemy import desc
from sqlalchemy.types import Enum as SQLEnum
from twilio.base.exceptions import TwilioRestException

from constants import (
    Decision, Error, Intent, JobStatus, LeaveType, MessageType, SelectionType, AuthorizedDecision
)
from extensions import db, get_session
from logs.config import setup_logger
from models.exceptions import ReplyError
from models.jobs.abstract import Job
from models.jobs.unknown.unknown import JobUnknown
from models.jobs.user.abstract import JobUser
from models.leave_records import LeaveRecord
from models.messages.abstract import Message
from models.messages.received import MessageReceived, MessageSelection
from models.messages.sent import MessageSent
from models.users import User
from overrides import overrides
from utilities import join_with_commas_and, log_instances

class JobUser(Job): # Abstract class

    logger = setup_logger('models.job_user')
    max_pending_duration = timedelta(minutes=1)

    __tablename__ = 'job_user'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    name = db.Column(db.String(80), nullable=True) # dont create relationship otherwise the name is gone after deleted
    
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

    def __init__(self, name, job_no=None):
        super().__init__(job_no)
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

    def handle_authorisation(self, selection):
        if selection == Decision.APPROVE:
            self.handle_approve()
        else:
            self.handle_reject()
    
    def get_selection(self, ref_msg, raw_selection):

        if not raw_selection:
            raise ReplyError("Undetected Selection")
        
        selection_type = ref_msg.get_selection_type() # selection_type is Decision, LeaveType, or AuthorizedDecision

        if not selection_type:
            raise ReplyError(Error.UNKNOWN_ERROR)
        
        selection = selection_type(int(raw_selection))
        
        return selection_type, selection
    
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

    def handle_job_expiry(self):
        pass

    def get_cancel_intent(self):
        pass

# IMPT must separate because
# 1. cancel and authorize jobs must point to a general class and not JobLeave.
# 2. Cannot put relation on JobUser because otherwise JobCancel will have its own cancel jobs.

class JobUserInitial(JobUser): 
    __tablename__ = "job_user_initial"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    forwards_status = db.Column(SQLEnum(JobStatus), default=None, nullable=True)
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)
    auth_status = db.Column(SQLEnum(AuthorizedDecision), nullable=False)
    cancelled_job_no = db.Column(db.ForeignKey("job_user.job_no"), nullable=True)



    cancelled_job_no = db.Column(db.ForeignKey("job_cancel.job_no"), unique=True, nullable=True)
    # authorize_job_no = 
    cancelled_job = db.relationship('JobUserCancel', foreign_keys=[cancelled_job_no], backref=db.backref('original_job', uselist=False, remote_side=[JobLeaveCancel.job_no]), lazy='select')

    __mapper_args__ = {
        "polymorphic_identity": "job_user_initial"
    }

    def __init__(self, name):
        super().__init__(name)
        self.name = name

    @classmethod
    def create_new_job(cls, user_str, name):
        intent = MessageReceived.check_for_intent(user_str)
        if intent == Intent.ES_SEARCH or intent == None:
            raise ReplyError(Error.ES_REPLY_ERROR)

        job = cls.create_job(intent, user_str, name)
        return job

    @classmethod
    def general_workflow(cls, message, job_info):
        from models.messages.sent import MessageSent
        job = user = received_msg = selection = reply = None

        logging.info(f"Job information passed to general workflow from app.py and redis: {job_info}")
        sid = message['sid']
        user_str = message['user_str']
        raw_from_no = message['from_no']

        try:
            try:
                user = User.get_user(raw_from_no)
                if not user:
                    raise ReplyError(Error.USER_NOT_FOUND)
                
                # SECTION NEW JOB
                if not job_info:
                    job = cls.create_new_job(user_str, user.name)
                    received_msg = Message.create_message(MessageType.RECEIVED, job.job_no, sid, user_str)
                    
                else: # selection message
                    sent_sid = job_info.get("sent_sid", None)

                    replied_msg_sid = message.get('replied_msg_sid', None) # IMPT need to compare with sent_sid

                    ref_msg = MessageSent.get_message_by_sid(replied_msg_sid) # try to check the database
                    job = ref_msg.job # retrieve the job instance from ORM database
                    
                    raw_selection = message.get("selection", None) # numeric val
                    selection_type, selection = cls.get_selection(ref_msg, raw_selection)
                    job.update_info(job_info, selection_type, selection)

                    if job.user.number != user.number and job.status == JobStatus.PENDING_AUTHORISED_DECISION and job.user.reporting_officer == user.reporting_officer:
                        # IMPT is a authorised user!
                        pass

                    # SECTION By now, all messages HAVE selection.
                    # IMPT First handle msges whose cache has been cleared → missing sent_sid → valid only if cancelling.
                    
                    if not sent_sid: # LATE MSG: either TIMEOUTS or CANCEL OR SELECTION AFTER CANCEL
                        # TImeouts can only happen for PENDING_DECISION and PENDING_AUTHORISED_DECISION. If PENDING_AUTHORISED_DECISION timeouts, Redis Subscriber will handle the job
                        if selection and job.status == JobStatus.PENDING_DECISION: # CANCEL wont be during PENDING_DECISION
                            raise ReplyError(Error.TIMEOUT_MSG)
                        elif selection == Decision.CANCEL: # attempt CANCEL
                            details = job.get_cancel_details()
                            cancel_job = cls.create_job(job.cancel_intent, job)
                            reply = job.handle_cancellation(cancel_job, details) # IMPT fix necessary attr on cancel_job
                        else:
                            raise ReplyError(Error.JOB_COMPLETED) # likely because job is completed / failed / waiting for completion already

                    # NOT LAST MESSAGE
                    elif sent_sid != replied_msg_sid:
                        if job.status == JobStatus.PENDING_DECISION:
                            latest_sent_msg = MessageSelection.get_latest_sent_message(job.job_no) # probably not needed
                            if sent_sid != latest_sent_msg.sid:
                                raise ReplyError(job.errors.NOT_LAST_MSG) # TODO CAN CONSIDDER USER RETRYING
                            else:
                                raise ReplyError(Error.UNKNOWN_ERROR) # shouldnt happen but...
                        else:
                            raise ReplyError(Error.JOB_NOT_FOUND) # TODO really?
                    
                    else: # IMPT by now, sent_sid == replied_msg_sid. only can allow for confirm, cancel, or listitem
                        if job.status == JobStatus.PENDING_AUTHORISED_DECISION:
                            reply = job.handle_cancellation_before_authorisation() # TODO
                            # inform RO of cancellation
                            # remove from database
                            pass

                        elif job.status == JobStatus.PENDING_AUTHORISED_DECISION:
                            # throw error that cannot cancel when rejected
                            raise ReplyError(job.errors.CANCELLED_AFTER_REJECTION)

                        if job.status != JobStatus.PENDING_DECISION and job.status != JobStatus.PENDING_AUTHORISED_DECISION:
                            raise ReplyError(Error.UNKNOWN_ERROR)
                        
                        # Valid Replies
                        job.commit_status(JobStatus.PROCESSING)

                        if selection == Decision.CANCEL:
                            raise ReplyError(job.errors.CANCEL_MSG, job_status=JobStatus.CLIENT_ERROR)
                        elif (selection == AuthorizedDecision.APPROVE or selection == AuthorizedDecision.REJECT):
                            reply = job.handle_authorisation(selection) # TODO
                    
                    # CHECK if there was a cancel. # IMPT bypass_validation is currently ensuring that the user doesnt cancel when clicking on a list item
                    received_msg = Message.create_message(MessageType.CONFIRM, job.job_no, sid, user_str, replied_msg_sid, selection)
                            
                job.background_tasks = []
                job.user_str = user_str
                job.sent_msg = job.create_reply_msg(reply, received_msg) # TODO check if need job = job.handle_request()
                
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

                sent_msg = job.create_reply_msg(re.err_message, received_msg)

            job_data = {"job_no": job.job_no}  # passed to redis, which is used when updating status once callback is received
            if job and job.status == JobStatus.PROCESSING and getattr(sent_msg, 'selection_type', False): # may throw error due to leave_type empty but still processing
                job_data = {**job_data, **job.set_cache_data()}
                # job_data["selection_type"] = sent_msg.selection_type.value
                job_data['sent_sid'] = sent_msg.sid # passed to redis, which is used to check that the last message sent out is the message that is being replied to, when updating status to JobStatus.PENDING_DECISION once callback is received. Also used to ensure that in general_workflow, the sent_sid matches the replied to of the new message
                # job_data["status"] = job.status.value # passed to redis, which updates to JobStatus.PENDING_DECISION or JobStatus.PENDING_AUTHORISED_DECISION once callback is received
                if sent_msg.selection_type == SelectionType.AUTHORIZED_DECISION: 
                    # TODO catch no RO?
                    job_data["authoriser_number"] = job.user.reporting_officer.sg_number # Possible to have multiple?
            return job_data
   
        except Exception:
            logging.error("Something wrong with application code")
            logging.error(traceback.format_exc())
            if job and not getattr(job, "local_db_updated", None) and not job.status == JobStatus.OK:
                job.commit_status(JobStatus.SERVER_ERROR)
            raise

class JobUserCancel(JobUser):
    __tablename__ = "job_cancel"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    forwards_status = db.Column(SQLEnum(JobStatus), default=None, nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "job_cancel",
        'inherit_condition': (job_no == JobUser.job_no),
    }

    def __init__(self, initial_job, new_job_no):
        super().__init__(initial_job.user.name, new_job_no)
        self.initial_job_no = initial_job.job_no
        self.local_db_updated = False
        self.forwards_status = None
        
    @overrides
    def forward_messages(self):
        self.cv_list = self.get_forward_cancel_leave_cv()
        super().forward_messages()

        if len(self.successful_forwards) > 0:
            return f"messages have been successfully forwarded to {join_with_commas_and(self.successful_forwards)}. Pending delivery success..."
        else:
            return f"All messages failed to send. You might have to update them manually, sorry about that"
    
    # inherit
    # def handle_replied_future_results(self, future_results):

    # inherit
    # @overrides
    # def validate_complete(self):

from datetime import datetime, timedelta, date
from extensions import db, get_session
from constants import errors, LeaveType, LeaveIssue, leave_keywords, SelectionType, Decision, Intent, JobStatus
from dateutil.relativedelta import relativedelta
import os
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, join_with_commas_and, get_latest_date_past_9am, combine_with_key_increment
from overrides import overrides

from logs.config import setup_logger

from models.users import User
from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUser
from models.leave_records import LeaveRecord
import re
import traceback
from .utils_leave import dates
from sqlalchemy.types import Enum as SQLEnum

class JobAuthorise(JobUser):
    __tablename__ = "job_authorise"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    forwards_status = db.Column(db.Integer, default=None, nullable=True)
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_leave"
    }
