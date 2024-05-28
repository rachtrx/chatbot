import threading

class JobScheduler:
    def __init__(self):
        self.jobs = {}
        self.job_locks = {}

    def add_job(self, job):
        self.jobs[job.job_id] = job
        self.job_locks[job.job_id] = threading.Lock()

    def execute_job(self, job_id):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job_lock = self.job_locks[job_id]
            threading.Thread(target=self._run_job, args=(job, job_lock)).start()
        else:
            print(f"Job {job_id} not found")

    def _run_job(self, job, job_lock):
        with job_lock:
            job.execute()
