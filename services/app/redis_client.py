import json
import logging
from logs.config import setup_logger
from constants import JobStatus
from concurrent.futures import ThreadPoolExecutor
from models.jobs.user.abstract import JobUser
from models.exceptions import ReplyError
from models.users import User
from constants import Error, SelectionType
import redis
import traceback

class Redis():

    logger = setup_logger('models.redis')

    def __init__(self, url, cipher_suite):
        self.client = redis.Redis.from_url(url)
        self.cipher_suite = cipher_suite

    def get_last_job_info(self, user_id):
        encrypted_data = self.client.hget(f"user_job_data:{user_id}", "job_information")
        if encrypted_data:
            # Decrypt the data back into a JSON string
            decrypted_data_json = self.cipher_suite.decrypt(encrypted_data).decode()
            last_job_info = json.loads(decrypted_data_json)
            return last_job_info
        return None
    
    @staticmethod
    def catch_reply_errors(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ReplyError as re:
                job_info = kwargs['new_job_info']

                user = User.get_user(job_info['from_no'])
                if not user:
                    re.err_message = Error.USER_NOT_FOUND
                user_or_no = user if user else job_info['from_no']
                re.send_error_msg(sid=job_info['sid'], user_str=job_info['user_str'], user_or_no=user_or_no)
                return False
        return wrapper

    @catch_reply_errors
    def enqueue_job(self, user_id, new_job_info):
        # Use a list as a queue for each user's jobs
        job_enqueued = False

        # if the message was a reply, enqueue first
        if new_job_info.get('replied_msg_sid', None):
            job_enqueued = True
            
        # not a reply
        else:
            # else if current process running, raise error
            if self.client.get(f"user_job:{user_id}"):
                raise ReplyError(Error.DOUBLE_MESSAGE)
            # if no current process, check for last job
            else:
                last_job_info = self.get_last_job_info(user_id)
                if last_job_info:
                    # no process running, last job exists, user didn't send a reply
                    raise ReplyError(Error.PENDING_DECISION)
                # not a reply, no process running, no last job
                job_enqueued = True
        
        if job_enqueued:
            self.client.rpush(f"user_jobs_queue:{user_id}", json.dumps(new_job_info))
        
        return job_enqueued

    def job_completed(self, job_details, user_id):

        logging.info(f"job_details: {job_details}")

        if job_details is None:
            self.finish_job(user_id)
            logging.info("finished job!")
        else:
            job_completed_data_json = json.dumps(job_details)
            encrypted_data = self.cipher_suite.encrypt(job_completed_data_json.encode())
            self.client.hset(f"user_job_data:{user_id}", "job_information", encrypted_data)
            self.client.expire(f"user_job_data:{user_id}", JobUser.max_pending_duration)
            logging.info(f"job completed for user {user_id}")
            self.finish_job(user_id, clear_data=False)

    def finish_job(self, user_id, clear_data=True):
        # Clear the in-progress flag
        self.client.delete(f"user_job:{user_id}")
        if clear_data:
            logging.info("Clearing data for job")
            self.client.delete(f"user_job_data:{user_id}")
        self.start_next_job(user_id)

    def start_next_job(self, user_id):
        '''
        Called from 
        a) main thread when msg enqueued (new msg)
        b) after finish job (in case user double clicks confirm and cancel),
        c) after Twilio's callback whr msg has been updated to JobStatus.PENDING_DECISION

        possible jobs that have been enqueued: reply messages, new messages sent when no other job running or job pending
        '''
        # Check no job running
        if not self.client.get(f"user_job:{user_id}"):

            # check for pending job
            last_job_info = self.get_last_job_info(user_id)
            # new message must be a reply. dont start job if its not pending reply; the callback will start it
            if last_job_info and last_job_info['status'] != JobStatus.PENDING_DECISION: 
                return None
            
            # msg must be completely new / last job exists and is pending reply / user double clicks but the last_job_info has been deleted
            else:
                logging.info(f"start next job user_id: {user_id}")
                job_info_raw = self.client.lpop(f"user_jobs_queue:{user_id}")
                if job_info_raw:
                    new_job_info = json.loads(job_info_raw)
                    
                    if last_job_info:
                        new_job_info.update(last_job_info)  # Assuming you want to update/merge it
                    logging.info(f"Combined job info dict: {new_job_info}")

                    # Proceed with setting the job in progress and starting it
                    self.client.set(f"user_job:{user_id}", "in_progress", ex=JobUser.max_pending_duration)

                    logging.info("JOB STARTED")
                    job_info = JobUser.general_workflow(new_job_info)
                    self.job_completed(job_info, user_id)  # Assuming job_completed does not require parameters, or pass them if it does

                    return "job started", new_job_info
        # If there's already an job in progress or no jobs in the queue
        else:
            logging.info("JOB NOT READY TO START")
            return None

    def update_job_status(self, user_id, message):
        '''updates job status to pending user reply in the cache as soon as the callback has been confirmed'''
        encrypted_data = self.client.hget(f"user_job_data:{user_id}", "job_information")
        if encrypted_data:
            logging.info("Encrypted data found!")
            # Decrypt the data back into a JSON string
            decrypted_data_json = self.cipher_suite.decrypt(encrypted_data).decode()
            last_job_info = json.loads(decrypted_data_json)
            if isinstance(last_job_info, dict):
                if last_job_info.get("sent_sid", None) == message.sid and last_job_info.get("job_no", None) == message.job_no: # if current data found
                    if last_job_info['selection_type'] == SelectionType.DECISION:
                        last_job_info['status'] = JobStatus.PENDING_DECISION
                    elif last_job_info['selection_type'] == SelectionType.AUTHORISED_DECISION:
                        last_job_info['status'] = JobStatus.PENDING_AUTHORIZED_DECISION
                    logging.info("updated job status to pending user reply")
                    # Convert updated dictionary back to JSON and then encrypt it before storing
                    updated_data_json = json.dumps(last_job_info)
                    encrypted_updated_data = self.cipher_suite.encrypt(updated_data_json.encode())
                    self.client.hset(f"user_job_data:{user_id}", "job_information", encrypted_updated_data)
                    return last_job_info['status']