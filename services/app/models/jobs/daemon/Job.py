import os
import traceback

from extensions import Session, db

from models.users import User
from models.exceptions import UserNotFoundError, DaemonTaskError

from models.jobs.base.Job import Job
from models.jobs.base.constants import JobType, Status, ErrorMessage, MessageType, OutgoingMessageData
from models.jobs.base.utilities import convert_utc_to_sg_tz

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.tasks import AcquireToken, SyncUsers, SyncLeaves, SendReport, SendReminder, AutoApprove, CleanTasks
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

from models.messages.MessageKnown import MessageKnown

import os

class JobDaemon(Job):

    __tablename__ = 'job_daemon'
    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": JobType.DAEMON,
    }

    full_phone = os.environ.get('DEV_NO', None)
    phone_number = ''.join(filter(str.isdigit, full_phone))[-8:]

    def __init__(self, *args, **kwargs):
        self.logger.info("Creating Daemon Job")
        
        if not kwargs.get('primary_user_id'):
            # Start with a base query

            session = Session()

            user = session.query(User).filter(User.dept == 'ICT').filter(
                (User.name == 'ICT Hotline') | 
                (User.is_global_admin == True) | 
                (User.is_dept_admin == True)
            ).order_by(
                (User.name == 'ICT Hotline').desc(),  # Prioritize by name match first
                User.is_global_admin.desc(),          # Next, prioritize global admin
                User.is_dept_admin.desc()             # Lastly, prioritize dept admin
            ).first()

            if user:
                kwargs['primary_user_id'] = user.id
                super().__init__(*args, **kwargs)
            else:
                raise UserNotFoundError(os.getenv('DEV_NO'), ErrorMessage.NO_ADMINS_FOUND)
        

    def execute(self, tasks_to_run):

        self.tasks_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            DaemonTaskType.ACQUIRE_TOKEN: AcquireToken,
            DaemonTaskType.SYNC_USERS: SyncUsers,
            DaemonTaskType.SYNC_LEAVES: SyncLeaves,
            DaemonTaskType.SEND_REPORT: SendReport,
            DaemonTaskType.SEND_REMINDER: SendReminder,
            DaemonTaskType.AUTO_APPROVE: AutoApprove,
            DaemonTaskType.CLEAN_TASKS: CleanTasks
        } # IMPT to add more, need to update content template builder in Twilio, or can use 

        cv = {}

        self.logger.info(f"Tasks to run: {len(tasks_to_run)}")

        is_daily_update = DaemonTaskType.SEND_REPORT in tasks_to_run
        
        for task_type in tasks_to_run:
            self.run_task(task_type=task_type) # error is handled each time

        if is_daily_update:

            for i, task_type in enumerate(self.tasks_map.keys(), 1):

                latest_task = None
                latest_successful_task = None

                try:
                    self.logger.info(f"Task Type: {task_type}")
                    latest_task = TaskDaemon.get_latest_tasks(task_type=task_type, count=1)

                    if not latest_task:
                        self.logger.info("Process not ran before")
                        cv[str(i)] = "Process not ran before"
                    # Condition to check if there is a task and to update the status conditionally
                    else:
                        last_run_time = convert_utc_to_sg_tz(latest_task.created_at, '%d %b %y %H:%M')
                        if latest_task.status == Status.COMPLETED:
                            latest_successful_task = latest_task
                            last_success_run_time = last_run_time
                            cv[str(i)] = f"{last_success_run_time} / {last_run_time}"
                        else:
                            latest_successful_task = TaskDaemon.get_latest_completed_task(task_type=task_type)
                            if latest_successful_task:
                                last_success_run_time = convert_utc_to_sg_tz(latest_successful_task.created_at, '%d %b %y %H:%M')
                            else:
                                last_success_run_time = "All runs unsuccessful"

                            cv[str(i)] = f"*{last_success_run_time} / {last_run_time}*"

                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    cv[str(i)] = "Unknown Error Occured"

            self.logger.info(f"Content Vars: {cv}")
            self.logger.info(f"Daemon Main User ID: {self.primary_user_id}")

            message = OutgoingMessageData(
                msg_type=MessageType.SENT,
                user_id=self.primary_user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SEND_SYSTEM_STATUS_SID'),
                content_variables=cv
            )
            MessageKnown.send_msg(message=message)
        return True
    
    def run_task(self, task_type):
        task_class = self.tasks_map.get(task_type)
        # TODO catch errors?
        self.logger.info(f"Task Class: {task_class.__name__.lower()}")
        latest_task = task_class(self.job_no)
        try:
            self.logger.info(f"Running latest task")
            latest_task.run()
        except Exception as e:
            err_info = e.message if isinstance(e, DaemonTaskError) else DaemonMessage.UNKNOWN_ERROR
            err_msg = OutgoingMessageData(
                msg_type=MessageType.FORWARD,
                user_id=self.primary_user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SEND_SYSTEM_HEALTH_ERROR_SID'),
                content_variables={
                    '1': latest_task.name,
                    '2': err_info,
                }
            )
            MessageKnown.send_msg(err_msg)

    def handle_error(self, err_message: OutgoingMessageData, error):
        MessageKnown.send_msg(self.message)
        return
    


