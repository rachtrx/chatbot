import threading
from RedisQueue import RedisQueue
import time
from manage import create_app
from models.jobs.abstract import Job

app = create_app()

class BaseScheduler:
    def __init__(self, prefix):
        self.queues = {}
        self.workers = {}
        self.prefix = prefix
        self.lock = threading.Lock()

    def add_to_queue(self, item_id, message):
        with self.lock:  # Ensure thread-safe access to queues and workers
            if item_id not in self.queues:
                # Create a new queue for new job ID
                self.queues[item_id] = RedisQueue(f"{self.prefix}:{item_id}")
                # Start a new worker for this job ID
                self.start_worker_for_queue(item_id)
            # Add message to the appropriate queue
            self.queues[item_id].put(message)

    def start_worker_for_queue(self, item_id):
        worker_thread = threading.Thread(target=self.worker, args=(item_id,))
        worker_thread.start()
        self.workers[item_id] = worker_thread

    def worker(self, item_id):
        try:
            data = self.queues[item_id].get(block=False) # 1st message should be available
            print(f"Message data retrieved: {data}")
            while not self.queues[item_id].is_empty():
            # Wait for the next job message
                with app.app_context():
                    self.execute(item_id, data)
                data = self.queues[item_id].get(block=True, timeout=120) # reply should only come after the callback of message successful
        finally:
            self.cleanup_worker(item_id)

    def cleanup_worker(self, item_id):
        with self.lock:
            if item_id in self.queues:
                del self.queues[item_id]
                del self.workers[item_id]
                print(f"Cleaned up resources for job {item_id}")

class JobScheduler: # job queue
    def __init__(self, prefix='job'):
        super().__init__(prefix)

    def execute(self, job_id, message_data):
        print(f"Executing job {job_id} with data: {data}")
        # get the pipelinett
        job = Job.query.filter_by(job_no=job_id).first()
        job.restore_cache()
        job.preprocess(message_data)
        job.update_cache()
        user = job.user.id
        if reply_message:
            MessageScheduler.add_to_queue(user.id, reply_message) # hash identifier?

class MessageScheduler: # user queue
    def __init__(self, prefix='messages'):
        super().__init__(prefix)

    def execute(self, job_id, reply_message):
        print(f"Executing job {job_id} with data: {data}")
