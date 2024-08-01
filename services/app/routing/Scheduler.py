import threading
import logging

from manage import create_app
from extensions import Session

from routing.Redis import RedisQueue

from models.jobs.base.constants import JOBS_PREFIX
from models.jobs.base.Job import Job

from models.messages.MessageKnown import MessageKnown

from models.exceptions import ReplyError

class BaseScheduler:
    def __init__(self, prefix, max_workers=3):
        self.queues = {}
        self.workers = {}
        self.prefix = prefix
        self.lock = threading.Lock()
        self.worker_semaphore = threading.Semaphore(max_workers)  # Limit the number of workers

    def add_to_queue(self, item_id, payload):
        with self.lock:  # Ensure thread-safe access to queues and workers
            if item_id not in self.queues:
                # Create a new queue for new job ID
                self.queues[item_id] = RedisQueue(f"{self.prefix}:{item_id}")
                # Add payload to the appropriate queue
                self.queues[item_id].enqueue(payload)
                # Start a new worker for this job ID
                self.start_worker_for_queue(item_id)
            else:
                self.queues[item_id].enqueue(payload)
            

    def start_worker_for_queue(self, item_id):
        self.worker_semaphore.acquire()  # Wait indefinitely for a permit; blocking=True by default
        try:
            worker_thread = threading.Thread(target=self.worker, args=(item_id,))
            worker_thread.start()
            self.workers[item_id] = worker_thread
        except Exception as e:
            logging.info(f"Failed to start worker: {e}")
            self.worker_semaphore.release()

    def worker(self, item_id):
        try:
            session = Session()
            logging.info(f"Opening session in worker: {id(session)}")

            payload = self.queues[item_id].get(block=False)  # 1st message should be available. TODO handle error?
            logging.info(f"Payload retrieved: {payload}")

            completed = empty = False

            while not empty:
                # Execute job in the application context
                # Wait for msges
                with create_app().app_context():
                    completed = self.execute(item_id, payload) # job.execute must return True or False
                    if completed:
                        empty = self.queues[item_id].is_empty()
                        logging.info(f"Is empty: {empty}")
                        if empty:
                            break
                payload = self.queues[item_id].get(block=True, timeout=60)
                if payload is None:
                    break
        finally:
            logging.info(f"Closing session in worker: {id(session)}")
            session.close()
            self.cleanup_worker(item_id)
            self.worker_semaphore.release()  # Release the permit when the worker finishes

    def cleanup_worker(self, item_id):
        with self.lock:
            if item_id in self.queues:
                del self.queues[item_id]
                del self.workers[item_id]
                print(f"Cleaned up resources for item {item_id}")


class JobScheduler(BaseScheduler): # job queue

    def execute(self, job_id, payload): # MESSAGE / DAEMON
        logging.info(f"Executing job {job_id} with data: {payload}")

        # TODO WITH APP CONTEXT?
        session = Session()
        job = session.query(Job).get(job_id)
        try:
            return job.execute(payload) # implement whether the job can be cleaned up, for leave, once the requestor is no longer pending
        except ReplyError as re:
            re.execute()
        
job_scheduler = JobScheduler(prefix=JOBS_PREFIX)