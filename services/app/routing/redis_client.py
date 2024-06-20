import json
import logging
from MessageLogger import setup_logger
from constants import JobStatus
# from concurrent.futures import ThreadPoolExecutor
from models.jobs.user.abstract import JobUserInitial
from models.jobs.user.base import JobUserInitial
from models.exceptions import ReplyError
from models.users import User
from models.messages.sent import MessageSent
from constants import Error, SelectionType
import redis
import traceback
import threading
import hashlib
import shortuuid
import re
from utilities import get_session

# class RedisJob:
#     redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

#     def __init__(self, job_no):
#         self.job_no = job_no
#         self.job_key = f"job_data:{self.job_no}"

#     def set_job_field(self, field, value):
#         self.redis_client.hset(self.job_key, field, value)

#     def get_job_field(self, field):
#         value = self.redis_client.hget(self.job_key, field)
#         return value.decode('utf-8') if value else None

#     def set_multiple_job_fields(self, fields_values):
#         self.redis_client.hmset(self.job_key, fields_values)

#     def get_all_job_fields(self):
#         fields_values = self.redis_client.hgetall(self.job_key)
#         return {k.decode('utf-8'): v.decode('utf-8') for k, v in fields_values.items()}

#     def expire_job(self, expiration):
#         self.redis_client.expire(self.job_key, expiration)

#     def set_user_job(self, user_id, job_no, expiration):
#         user_job_key = f"user_job:{user_id}"
#         self.redis_client.set(user_job_key, job_no, ex=expiration)

#     def get_user_job(self, user_id):
#         user_job_key = f"user_job:{user_id}"
#         job_no = self.redis_client.get(user_job_key)
#         return job_no.decode('utf-8') if job_no else None

class Redis:

    logger = setup_logger('models.redis')

    def __init__(self, url, cipher_suite):
        self.client = redis.Redis.from_url(url)
        self.cipher_suite = cipher_suite
        self.subscriber = RedisSubscriber(self.client)  

    # Utility function setup
    def hash_identifier(identifier, salt=''):
        hasher = hashlib.sha256()
        hasher.update(f'{salt}{identifier}'.encode())
        return hasher.hexdigest()

    # def get_current_job_data(self, job_no):
    #     encrypted_data = self.client.get(f"job_information:{job_no}")

    #     if encrypted_data:
    #         # Decrypt the data back into a JSON string
    #         decrypted_data_json = self.cipher_suite.decrypt(encrypted_data).decode()
    #         last_job_info = json.loads(decrypted_data_json)
    #         return last_job_info
    #     return None
    
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
    
    def update_user_status(self, user_id, status=1):
        user_status_key = f"user:{user_id}:status"
        self.client.setex(user_status_key, JobUserInitial.max_pending_duration, status)

    def get_user_status(self, user_id):
        user_status_key = f"user:{user_id}:status"
        status = self.client.get(user_status_key)
        if status is not None:
            return int(status)
        return None

    def add_job_info(self, job_no, job_info={}):
        job_info_key = f"job:{job_no}:info"
        # Set job information
        encrypted_data = self.cipher_suite.encrypt(json.dumps(job_info).encode())
        self.client.set(job_info_key, encrypted_data)
        logging.info(f"Added job {job_no} with info {job_info}")

    def add_job(self, user_id, job_no):
        user_jobs_key = f"user:{user_id}:jobs"
        messages_key = f"job:{job_no}:messages:{user_id}"

        # Add job to user's job queue
        self.client.rpush(user_jobs_key, job_no)

        # Initialize messages list
        self.client.delete(messages_key)

    def get_next_job(self, user_id):
        user_jobs_key = f"user:{user_id}:jobs"
        job_no = self.client.lpop(user_jobs_key)
        if job_no:
            job_no = job_no.decode('utf-8')
        return job_no
    
    def get_current_job(self, user_id):
        user_jobs_key = f"user:{user_id}:jobs"
        job_no = self.client.lindex(user_jobs_key, 0) # most right
        if job_no:
            job_no = job_no.decode('utf-8')
        return job_no
    
    def clear_job_info(self, job_no):
        self.client.delete(f"job:{job_no}:info") # clear job info

    def clear_user_job_data(self, user_id, job_no):
        self.client.delete(f"job:{job_no}:messages:{user_id}") # clear messages
        self.client.lrem(f"user:{user_id}:jobs", 1, job_no)

    def add_message(self, user_id, job_no, message):
        messages_key = f"job:{job_no}:messages:{user_id}"
        self.client.rpush(messages_key, json.dumps(message))
        logging.info(f"Added message to job {job_no} for user {user_id}: {message}")

    def get_next_message(self, user_id, job_no):
        messages_key = f"job:{job_no}:messages:{user_id}"
        message = self.client.lpop(messages_key)
        if message:
            message = json.loads(message)
            logging.info(f"Dequeued message from job {job_no} for user {user_id}: {message}")
        return message
    
    def push_message_back(self, user_id, job_no, message):
        queue_key = f"job:{job_no}:messages:{user_id}"
        self.client.lpush(queue_key, json.dumps(message))

    def get_job_info(self, job_no):
        job_info_key = f"job:{job_no}:info"
        
        encrypted_data = self.client.get(job_info_key)
        if encrypted_data:
            # Decrypt the data back into a JSON string
            decrypted_data_json = self.cipher_suite.decrypt(encrypted_data).decode()
            last_job_info = json.loads(decrypted_data_json)
            return last_job_info
        return None

    def move_job_to_front(self, user_id, job_no):
        user_jobs_key = f"user:{user_id}:jobs"

        # Check if the job is already at the front
        if job_no != self.client.lindex(user_jobs_key, 0).decode('utf-8'):
            # Retrieve the entire queue
            queue = self.client.lrange(user_jobs_key, 0, -1)
            
            # Convert bytes to strings
            queue = [item.decode('utf-8') for item in queue]

            # Find and remove the job from the list
            if job_no in queue:
                queue.remove(job_no)

            # Start a pipeline to ensure atomicity
            with self.client.pipeline() as pipe:
                # Push the job to the front of the queue
                pipe.lpush(user_jobs_key, job_no)

                # Re-add the remaining items back to the queue
                for item in reversed(queue):
                    pipe.rpush(user_jobs_key, item)

                # Execute the pipeline
                pipe.execute()

    def update_job_info(self, job_no, new_data):
        job_info = self.get_job_info(job_no)
        self.add_job_info({**job_info, **new_data})

    @catch_reply_errors
    def enqueue_job(self, user_id, new_message_data):
        # Use a list as a queue for each user's jobs

        # if the message was a reply, enqueue first
        if new_message_data.replied_msg_sid:
            ref_msg = MessageSent.get_message_by_sid(new_message_data.replied_msg_sid) # try to check the database
            job = ref_msg.job
            self.update_job_info(job.job_no, new_message_data)
            self.move_job_to_front(user_id, job.job_no)
        else: # new message
            if self.get_current_job(user_id): # no process running, last job exists, user didn't send a reply
                raise ReplyError(Error.PENDING_DECISION)
            elif self.get_user_status(user_id): # else if current process running, raise error
                raise ReplyError(Error.DOUBLE_MESSAGE)
            else:
                # not a reply, no process running, no last job
                job_no = shortuuid.ShortUUID().random(length=8)
                self.add_job(user_id, job_no)
                self.add_job_info(job_no)

        self.add_message(user_id, job_no, new_message_data.__dict__)    
        return True # TODO isit always return True?

    def job_completed(self, job_details, user_id):

        job_no = job_details.pop('job_no')

        if not job_details: # evaluates to false if its an empty dict
            
            self.add_job_info(job_no, job_details)
            # KEEP USER_JOB_DATA!

            if 'authoriser_number' in job_details:
                new_user_id = self.hash_identifier(str(job_details['authoriser_number'])) # IMPT if expecting authorisation, shift the cache to store for RO
                self.add_job(new_user_id, job_no) # pass to RO
                self.clear_user_job_data(user_id, job_no)
                logging.info(f"job saved in cache for {job_no}")
            
        else: # not expecting reply
            logging.info("Clearing data for job")
            self.clear_user_job_data(user_id, job_no)
            self.clear_job_info(job_no)
            
            logging.info(f"job completed for {job_no}")

        self.client.delete(f"user:{user_id}:status") # clear user status
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
        user_status = self.get_user_status(user_id)
        if user_status: 
            return
        
        job_no = self.get_current_job(user_id) # cycle each job and check that it is still valid in the cache
        if not job_no: # no jobs
            return None      

        job_info = new_msg = None # either job_info or received msg has to be present at any time in the cache, so cycle each job and check that it is still valid in the cache
        while True: # IMPT will it reject the empty dictionary when job is initialised too??
            job_no = self.get_current_job(user_id)
            if not job_no: # no jobs
                return None
            job_info = self.get_job_info(job_no)
            new_msg = self.get_next_message(user_id, job_no) # Proceed with setting the job in progress and starting it
            if job_info or new_msg:
                break
            self.clear_user_job_data(user_id, job_no) # loop and delete jobs with neither

        if not new_msg: # needs a new msg
            # cannot get next job as selection might not have been sent. only get when job is DELETED or COMPLETED
            return None

        # TODO GET JOB STATUS, DONT USE job_info['status'], its deprecated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   

        # might be NEW MESSAGE or REPLY or REPLY AFTER EXPIRY
        # new message, job_info optional (for quick replies)
        # job not pending reply; the callbacks will start it. Note the status cannot be others because only PENDING messages are cached...
        if job_info and job_info['status'] != JobStatus.PENDING_DECISION and job_info['status'] != JobStatus.PENDING_AUTHORISED_DECISION: 
            self.push_message_back(user_id, job_no, new_msg)
            return None
        else: # last job exists and is pending selection / user double clicks but the last_job_info has been deleted
            logging.info(f"Combined job info dict: {new_msg}")
            logging.info("JOB STARTED")
            # OK

        self.update_user_status(user_id)
        job_info = JobUserInitial.general_workflow(new_msg, job_info)
        self.job_completed(job_info, user_id) # Assuming job_completed does not require parameters, or pass them if it does

        return "job started", new_msg
    
    def send_next_msg_to_user(self, user_id):
        # before sending msg, check current job for user

        # if theres a current job that is not the same job, dont send
        # else send message

        # move job to start of the queue
        message_key = f"user:messages:{user_id}"
        
        if self.get_current_job(user_id) != 
        reply = self.client.lpop(message_key, user_id)
        from models.messages.sent import MessageSent
        MessageSent.execute(reply) # TODO

    def add_pending_message_to_user_queue(self, user_id):
        message_key = f"user:messages:{user_id}"
        self.client.rpush(message_key, user_id)
        self.send_next_msg_to_user(user_id)
        

    def check_for_complete(self, job):
        job_info = self.get_job_info(job.job_no)
        if job_info['status'] == JobStatus.PENDING_CALLBACK:
            job.commit_status(JobStatus.OK)


    #### NEW VERSION #####

    def push_to_primary_queue(self, user_id):
        
class RedisSubscriber:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.psubscribe('__keyevent@0__:expired')
        self.pubsub.psubscribe('__keyevent@0__:del')

    def listen(self):
        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                event_type = message['channel'].decode('utf-8').split(':')[-1]
                key = message['data'].decode('utf-8')
                self.handle_event(event_type, key)

    def handle_event(self, event_type, key):
        if event_type == 'expired':
            self.handle_expired_key(key)
        elif event_type == 'del':
            self.handle_deleted_key(key)

    def handle_expired_key(self, key):
        logging.info(f"Key expired: {key}")
        # Add your custom action here
        match = re.match(r"job:(\w+):info", key)
        if match:
            job_no = match.group(1)
            session = get_session()
            job = session.query(JobUserInitial).filter(JobUserInitial.job_no == job_no).first()
            job.handle_job_expiry()


        