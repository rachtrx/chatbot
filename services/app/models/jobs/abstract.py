from extensions import db, get_session, remove_thread_session
from sqlalchemy import inspect
import shortuuid
import logging
from constants import MessageType, Error, JobStatus, SentMessageStatus, SystemOperation, Intent, ForwardStatus
from utilities import current_sg_time, join_with_commas_and, log_instances, run_new_context
import json
import os
import threading
from datetime import datetime, timedelta
from models.users import User
from datetime import datetime, timedelta
import logging

from models.exceptions import ReplyError
from MessageLogger import setup_logger
import traceback
from concurrent.futures import ThreadPoolExecutor
import time
from models.users import User

from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageSelection
from sqlalchemy.types import Enum as SQLEnum

class Job(db.Model): # system jobs

    __abstract__ = True
    logger = setup_logger('models.job')

    job_no = db.Column(db.String, primary_key=True)
    type = db.Column(SQLEnum(SystemOperation, Intent), nullable=False)
    status = db.Column(SQLEnum(JobStatus), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True))
    locked = db.Column(db.Boolean(), nullable=False)
    name = db.Column(db.String(80), nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": None,
        "polymorphic_on": "type"
    }

    def __init__(self, job_no=None, name=None):
        logging.info(f"current time: {current_sg_time()}")
        self.job_no = job_no or shortuuid.ShortUUID().random(length=8)
        self.logger.info(f"new job: {self.job_no}")
        self.created_at = current_sg_time()
        self.status = JobStatus.PROCESSING
        self.name = name
        self.locked = False

    def unlock(self, session):
        self.locked = False
        session.commit()

    def lock(self, session):
        self.locked = True
        session.commit()

    @property
    def user(self):
        if not getattr(self, '_user', None):
            session = get_session()
            self.user = session.query(User).filter_by(name=self.name).first()
        return self._user

    @user.setter
    def user(self, value):
        self._user = value

    @classmethod
    def create_job(cls, intent, *args, **kwargs):
        new_job = None
        if isinstance(intent, SystemOperation):
            if intent == SystemOperation.MAIN:
                new_job = cls(*args, **kwargs)
            elif intent == SystemOperation.ACQUIRE_TOKEN:
                from .system.acq_token import JobAcqToken
                new_job = JobAcqToken(*args, **kwargs)
            elif intent == SystemOperation.AM_REPORT:
                from .system.am_report import JobAmReport
                new_job = JobAmReport(*args, **kwargs)
            # Add conditions for other subclasses
            elif intent == SystemOperation.SYNC_USERS:
                from .system.sync_users import JobSyncUsers
                new_job =  JobSyncUsers(*args, **kwargs)
            elif intent == SystemOperation.SYNC_LEAVE_RECORDS:
                from .system.sync_leave_records import JobSyncRecords
                new_job =  JobSyncRecords(*args, **kwargs)
            elif intent == SystemOperation.INDEX_DOCUMENT:
                pass # TODO
        elif isinstance(intent, Intent):
            '''args is typically "user" and "options"'''
            if intent == Intent.CANCEL:
                from .user import JobUserCancel
                new_job = JobUserCancel(*args, **kwargs)
            elif intent == Intent.AUTHORISE:
                from .user import JobUserAuthorise
                new_job = JobUserAuthorise(*args, **kwargs)
            if intent == Intent.TAKE_LEAVE:
                from .user.leave import JobLeave
                new_job = JobLeave(*args, **kwargs)
            # Add conditions for other subclasses
            elif intent == Intent.ES_SEARCH:
                from .user.es import JobEs
                new_job =  JobEs(*args, **kwargs)
            elif intent == Intent.OTHERS:
                new_job =  cls(*args, **kwargs)
        if not new_job:
            raise ValueError(f"Unknown intent: {intent}")
        new_job.error = False
        session = get_session()
        session.add(new_job)
        session.commit()
        return new_job

    def all_messages_successful(self):
        '''also checks for presence of the other confirm option'''

        session = get_session()

        session.refresh(self)

        all_msgs = self.messages

        all_replied = True

        for i, msg in enumerate(all_msgs):
            if isinstance(msg, MessageSent):
                self.logger.info(f"Message {i+1}: {msg.body}, status={msg.status}")
                if msg.status != SentMessageStatus.OK: # TODO decide on whether to check for NOT OK instead!
                    all_replied = False
                    break
            
        if all_replied == True and self.status < 400:
            return True
        return False

    # to implement
    def validate_complete(self):
        if self.status == JobStatus.OK and self.all_messages_successful():
            return True
        return False

    def set_cache_data(self):
        pass

    

    def cleanup_on_error(self):
        pass
        

    def commit_status(self, status):
        '''tries to update status'''

        session = get_session()
        log_instances(session, "commit_status")

        if status is None:
            return
        elif status is JobStatus.SERVER_ERROR or status is JobStatus.CLIENT_ERROR:
            self.cleanup_on_error()
            self.logger.info(traceback.format_exc())
        
        self.status = status
        session.commit()

        job2 = session.query(Job).filter_by(job_no=self.job_no).first()
        logging.info(f"job no: {job2.job_no}")

        logging.info(f"Status in commit status: {job2.status}, status passed: {status}")

        return
    
    @run_new_context(wait_time = 5)
    def update_user_on_forwards(self, message_type, seq_no, use_name_alias):
        statuses = self.check_message_forwarded(seq_no)

        content_variables = {
            '1': message_type,
            '2': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.OK]) if len(statuses.OK) > 0 else "NA",
            '3': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.SERVER_ERROR]) if len(statuses.SERVER_ERROR) > 0 else "NA",
            '4': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.PENDING_CALLBACK]) if len(statuses.PENDING_CALLBACK) > 0 else "NA"
        }
        
        content_variables = json.dumps(content_variables)

        reply = (os.environ.get("FORWARD_MESSAGES_CALLBACK_SID"), content_variables)
        MessageForward.send_msg(MessageType.SENT, reply, self)
    
    def check_message_forwarded(self, seq_no):

        session = get_session()
        logging.info(f"session id in check_message_forwarded: {id(session)}")

        for instance in session.identity_map.values():
            logging.info(f"Instance in check_message_forwarded session: {instance}")

        try:
            logging.info("in threading function")

            forwarded_msgs = session.query(MessageForward).filter(
                MessageForward.job_no == self.job_no,
                MessageForward.seq_no == seq_no,
            ).all()

            if not forwarded_msgs:
                return

            # logging.info([f_msg.forward_status, f_msg.sid] for f_msg in forwarded_msgs)
            logging.info(list([f_msg.status, f_msg.sid] for f_msg in forwarded_msgs))

            statuses = ForwardStatus()
            for f_msg in forwarded_msgs:

                if f_msg.status == SentMessageStatus.OK:
                    statuses.OK.append(f_msg.to_user)
                elif f_msg.status == SentMessageStatus.SERVER_ERROR:
                    statuses.SERVER_ERROR.append(f_msg.to_user)
                else: # TODO ENSURE PENDING_CALLBACK
                    statuses.PENDING_CALLBACK.append(f_msg.to_user)
            return statuses
            
        except Exception as e:
            logging.error(traceback.format_exc())
            raise


    def update_with_msg_callback(self, status, sid, message):

        from models.messages.abstract import Message
        
        if (message.status != SentMessageStatus.PENDING_CALLBACK):
            logging.info("message was not expecting a reply")
            return None
        
        if status == "sent" and message.body is None:
            outgoing_body = Message.fetch_message(sid)
            logging.info(f"outgoing message: {outgoing_body}")
            message.commit_message_body(outgoing_body)

        elif status == "delivered":

            message.commit_status(SentMessageStatus.OK)
            logging.info(f"message {sid} committed with ok")

            if message.selection_type: # update redis to PENDING_DECISION?
                logging.info(f"expected reply message {sid} was sent successfully")
                return message
            
            if message.type == "message_forward":
                logging.info(f"forwarded message {sid} was sent successfully")
                if self.forwards_status_sent(message.seq_no):
                    self.update_user_on_forwards(message.seq_no, self.map_job_type())

            # reply message expecting user reply. just to be safe, specify the 2 types of messages
        
        elif status == "failed":
            # job immediately fails
            message.commit_status(SentMessageStatus.SERVER_ERROR)

            if message.type == "message_forward" and self.forwards_status_sent():
                self.update_user_on_forwards(message.seq_no, self.map_job_type())
            else:
                self.commit_status(JobStatus.SERVER_ERROR) # forward message failed is still ok to some extent, especially if the user cancels afterwards. It's better to inform about the cancel


            if self.type == "job_es": # TODO should probably send to myself
                Message.send_msg(MessageType.SENT, (os.environ.get("ERROR_SID"), None), self)

        return None
    
    def map_job_type(self):
        from models.jobs.user.leave import JobLeave, JobLeaveCancel
        from models.jobs.system.abstract import JobSystem

        if isinstance(self, JobLeave):
            return "your leave"
        
        if isinstance(self, JobLeaveCancel):
            return "your leave cancellation"
        
        elif isinstance(self, JobSystem):
            return self.type

    def run_background_tasks(self):
        if not getattr(self, "background_tasks", None) or len(self.background_tasks) == 0:
            return
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            for func, args in self.background_tasks:
                executor.submit(func, *args)


    @staticmethod
    def loop_relations(func):
        '''This wrapper wraps any function that takes in a user and loops over their relations.
        
        Returns a list of each relation function call result if there are relations, returns None if no relations.
        
        The function being decorated has a must have relation as the first param such that it can use the relation, but when calling it, it will take in the user'''
        
        def wrapper(job, *args, **kwargs):

            assert (isinstance(job, User) or isinstance(job, Job)), "job must be an instance of User or Job"

            if isinstance(job, User):
                relations = job.get_relations()
            else:
                relations = job.user.get_relations()

            job.relations_list = relations

            if all(relation is None for relation in job.relations_list):
                raise ReplyError(Error.NO_RELATIONS)
            
            results_list = []

            for relation in job.relations_list:
                if relation is None:
                    continue

                result = func(job, relation, *args, **kwargs)
                results_list.append(result) # original function has to be called on an instance method of job pr user
            
            return results_list
        return wrapper
    

    ######################################################
    # FOR SENDING SINGLE REPLY MSG ABT ALL THEIR RELATIONS
    ######################################################
    
    def print_relations_list(self):
        user_list = []
        for alias, number in self.get_relations_alias_and_no_list():
            user_list.append(f"{alias} ({number})")

        return join_with_commas_and(user_list)

    
    @loop_relations
    def get_relations_alias_and_no_list(self, relation):
        '''With the decorator, it returns a list as [(relation_name, relation_number), (relation_name, relation_number)]'''
        return (relation.alias, str(relation.number))
    

    ###################################
    # HANDLE USER REPLY
    ###################################


    def forward_messages(self):
        '''
        Ensure self has the following attributes: cv_list, which is usually created with a function under a @JobUserInitial.loop_relations decorator
        It is also within loop_relations that relations_list is set
        '''

        from models.messages.sent import MessageForward

        self.cv_and_users_list = list(zip(self.cv_list, self.relations_list)) # relations list is set in the loop relations decorator
        
        for i, (cv, user) in enumerate(self.cv_and_users_list):
            self.cv_and_users_list[i] = (json.dumps(cv), user)

        self.logger.info(f"forwarding messages with this cv list: {self.cv_and_users_list}")

        MessageForward.forward_template_msges(self)

        if len(self.successful_forwards) > 0:
            return f"messages have been successfully forwarded to {join_with_commas_and(self.successful_forwards)}. Pending delivery success..."
        else:
            return f"All messages failed to send. You might have to update them manually, sorry about that"

        # print(f"Job nos to delete: {job_nos}")
        # logging.info(f"Job nos to delete: {job_nos}")


class Job:
    def __init__(self, job_id):
        self.job_id = job_id
        self.processes = []
        self.queue = RedisQueue(name=f"job:{job_id}:queue")

    def add_process(self, process):
        self.processes.append(process)

    def execute(self):
        print(f"Executing job: {self.job_id}")
        while self.queue.qsize() > 0:
            message = self.queue.get()
            if message:
                self._execute_processes(message)

    def _execute_processes(self, message):
        results = []
        for process in self.processes:
            result = process.execute(message)
            results.append(result)
        self._send_results_to_users(results)

    def _send_results_to_users(self, results):
        for result in results:
            user_id = result['user_id'] # provided by the process
            response_queue = RedisQueue(name=f"user:{user_id}:responses")
            response_queue.put(result)
            print(f"Result sent to user {user_id}: {result}")