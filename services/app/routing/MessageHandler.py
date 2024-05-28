class MessageHandler:
    def __init__(self, job_scheduler):
        self.job_scheduler = job_scheduler

    def handle_message(self, message): # enqueue only

        user = User.get_user(message.from_no)
        if not user:
            raise ReplyError(Error.USER_NOT_FOUND)
        
        if message.replied_msg_sid:
            ref_msg = MessageSent.get_message_by_sid(message.replied_msg_sid)
            main_process = ref_msg.job.main_process
        
        process_name = message.get('name')
        process_type = message.get('type')
        action = message.get('action')

        if not job_id or not process_name or not process_type or not action:
            raise ValueError("Message must contain 'job_id', 'name', 'type', and 'action'")

        if action == 'add':
            self.add_process_to_job(job_id, process_name, process_type)
        elif action == 'enqueue':
            self.enqueue_message(job_id, message)
        elif action == 'execute':
            self.execute_job(job_id)
        else:
            raise ValueError(f"Unknown action: {action}")

        return {"status": "Task processed successfully"}

    def add_process_to_job(self, job_id, process_name, process_type):
        process = self.create_process(process_name, process_type)
        if job_id in self.job_scheduler.jobs:
            self.job_scheduler.jobs[job_id].add_process(process)
        else:
            job = Job(job_id)
            job.add_process(process)
            self.job_scheduler.add_job(job)
        print(f"Process {process_name} of type {process_type} added successfully to job {job_id}")

    def enqueue_message(self, job_id, message):
        if job_id in self.job_scheduler.jobs:
            self.job_scheduler.jobs[job_id].queue.put(message)
            print(f"Message enqueued to job {job_id}")
        else:
            print(f"Job {job_id} not found")

    def execute_job(self, job_id):
        self.job_scheduler.execute_job(job_id)
        print(f"Job {job_id} executed")

    def create_process(self, name, type):
        if type == 'data_cleaning':
            return DataCleaningProcess(name)
        elif type == 'data_transformation':
            return DataTransformationProcess(name)
        elif type == 'model_training':
            return ModelTrainingProcess(name)
        else:
            raise ValueError(f"Unknown process type: {type}")