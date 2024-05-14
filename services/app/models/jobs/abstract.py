from extensions import db, get_session, remove_thread_session
from sqlalchemy import inspect
import shortuuid
import logging
from constants import MessageType, Error, JobStatus, SentMessageStatus
from utilities import current_sg_time, join_with_commas_and, log_instances
import json
import os
import threading

from models.exceptions import ReplyError
from logs.config import setup_logger
import traceback
from concurrent.futures import ThreadPoolExecutor
import time
from models.users import User

from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageSelection

from functools import wraps
from sqlalchemy.types import Enum as SQLEnum

class Job(db.Model): # system jobs

    logger = setup_logger('models.job')

    __tablename__ = 'job'

    job_no = db.Column(db.String, primary_key=True)
    type = db.Column(db.String(50))
    status = db.Column(SQLEnum(JobStatus), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True))
    locked = db.Column(db.Boolean(), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job",
        "polymorphic_on": "type"
    }

    def __init__(self):
        logging.info(f"current time: {current_sg_time()}")
        self.job_no = shortuuid.ShortUUID().random(length=8)
        self.logger.info(f"new job: {self.job_no}")
        self.created_at = current_sg_time()
        self.status = JobStatus.PROCESSING
        self.locked = False

    def unlock(self, session):
        self.locked = False
        session.commit()

    def lock(self, session):
        self.locked = True
        session.commit()

    # BUG
    @staticmethod
    def run_new_context(wait_time=None):
        def decorator(func):
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                from manage import create_app

                result = None

                # logging.basicConfig(
                #     filename='/var/log/app.log',  # Log file path
                #     filemode='a',  # Append mode
                #     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
                #     level=logging.ERROR  # Log level
                # )

                if wait_time:
                    time.sleep(wait_time)

                app = create_app()
                with app.app_context():
                    session = get_session()
                    logging.info("In decorator")

                    try:
                        for _ in range(300):
                            updated_job = session.query(Job).filter_by(job_no = self.job_no).first()
                            if not updated_job.locked:
                                break
                        if not updated_job.locked:
                            log_instances(session, "run_new_context")
                            updated_job.lock(session)
                            session.commit()
                        else:
                            raise Exception                            

                        logging.info(id(session))
                        result = func(updated_job, *args, **kwargs)
                    
                        if isinstance(updated_job, Job):
                            updated_job.unlock(session)

                        logging.info(f"Result in decorator: {result}")

                    except Exception as e:
                        session.rollback()
                        logging.error("Something went wrong! Exception in decorator")
                        logging.error(traceback.format_exc())
                        raise
                    finally:
                        logging.info(id(session))
                        if threading.current_thread() == threading.main_thread():
                            logging.info("This is running in the main thread.")
                        else:
                            logging.info("This is running in a separate thread.")
                            remove_thread_session()
                        return result
            return wrapper
        return decorator

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
        return True

    def set_cache_data(self):
        pass

    def check_for_complete(self):
        session = get_session()
        if self.status == JobStatus.OK:
            return
        complete = self.validate_complete()
        self.logger.info(f"complete: {complete}")
        if complete:
            self.commit_status(JobStatus.OK)
        session.commit()
        

    def commit_status(self, status, _forwards=False):
        '''tries to update status'''

        session = get_session()
        log_instances(session, "commit_status")

        if status is None:
            return
        elif status is JobStatus.SERVER_ERROR or status is JobStatus.CLIENT_ERROR:
            self.logger.info(traceback.format_exc())
        
        if not _forwards:
            self.status = status
        else:
            self.forwards_status = status
        session.commit()

        job2 = session.query(Job).filter_by(job_no=self.job_no).first()
        logging.info(f"job no: {job2.job_no}")

        logging.info(f"Status in commit status: {job2.status if not _forwards else job2.forwards_status}, status passed: {status}")

        return

    def forward_status_not_null(self):
        if self.forwards_status == None:
            return False
        return True
    
    @run_new_context(wait_time = 5)
    def check_message_forwarded(self, seq_no, _type, alias=False):

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

            success = []
            failed = []
            unknown = []
            for f_msg in forwarded_msgs:
                if alias:
                    to_name = f_msg.to_user.alias

                if f_msg.status == SentMessageStatus.OK:
                    success.append(to_name)
                elif f_msg.status == SentMessageStatus.SERVER_ERROR:
                    failed.append(to_name)
                else:
                    unknown.append(to_name)

            content_variables = {
                '1': _type,
                '2': join_with_commas_and(success) if len(success) > 0 else "NA",
                '3': join_with_commas_and(failed) if len(failed) > 0 else "NA",
                '4': join_with_commas_and(unknown) if len(unknown) > 0 else "NA"
            }
            
            content_variables = json.dumps(content_variables)

            reply = (os.environ.get("FORWARD_MESSAGES_CALLBACK_SID"), content_variables)

            MessageForward.send_msg(MessageType.SENT, reply, self)

            if not len(failed) > 0 and not len(unknown) > 0: 
                self.commit_status(JobStatus.OK, _forwards=True)
            elif len(unknown) > 0:
                self.commit_status(JobStatus.PROCESSING, _forwards=True)
            else:
                self.commit_status(JobStatus.SERVER_ERROR, _forwards=True)
            
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
                if self.forward_status_not_null():
                    self.check_message_forwarded(message.seq_no, self.map_job_type())

            message.job.check_for_complete()

            
            # reply message expecting user reply. just to be safe, specify the 2 types of messages
        
        elif status == "failed":
            # job immediately fails
            message.commit_status(SentMessageStatus.SERVER_ERROR)

            if message.type == "message_forward" and self.forward_status_not_null():
                self.check_message_forwarded(message.seq_no, self.map_job_type())
            else:
                self.commit_status(JobStatus.SERVER_ERROR) # forward message failed is still ok to some extent, especially if the user cancels afterwards. It's better to inform about the cancel


            if self.type == "job_es": # TODO should probably send to myself
                Message.send_msg(MessageType.SENT, (os.environ.get("ERROR_SID"), None), self)

        return None
    
    def map_job_type(self):
        from models.jobs.user.leave import JobLeave, JobLeaveCancel
        from models.jobs.system.abstract import JobSystem

        if isinstance(self, JobLeave):
            if isinstance(self, JobLeaveCancel):
                return "your leave cancellation"
            return "your leave"
        
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
        Ensure self has the following attributes: cv_list, which is usually created with a function under a @JobUser.loop_relations decorator
        It is also within loop_relations that relations_list is set
        '''

        from models.messages.sent import MessageForward

        self.cv_and_users_list = list(zip(self.cv_list, self.relations_list)) # relations list is set in the loop relations decorator
        
        for i, (cv, user) in enumerate(self.cv_and_users_list):
            self.cv_and_users_list[i] = (json.dumps(cv), user)

        self.logger.info(f"forwarding messages with this cv list: {self.cv_and_users_list}")

        MessageForward.forward_template_msges(self)
            

          