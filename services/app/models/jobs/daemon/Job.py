import traceback
from datetime import datetime, timedelta

from sqlalchemy import not_, exists, and_
from sqlalchemy import func, not_, exists, and_
from sqlalchemy.sql import window

from models.jobs.base.Job import BaseJob
from models.jobs.base.constants import JobType, Status, OutgoingMessageData, MessageType
from models.jobs.base.utilities import get_session, convert_utc_to_sg_tz

from models.jobs.daemon.Task import DaemonTask
from models.jobs.daemon.tasks import AcquireToken, SyncUsers, SyncLeaves, SendReport
from models.jobs.daemon.constants import DaemonTaskType

from models.messages.MessageKnown import MessageKnown

import os

class JobDaemon(BaseJob):

    __mapper_args__ = {
        "polymorphic_identity": JobType.DAEMON,
    }

    sid = os.environ.get('SEND_SYSTEM_TASKS_SID')

    def execute(self, tasks_to_run):
        session = get_session()
        self.cv = {}
        self.delete_old_jobs()

        tasks_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            DaemonTaskType.ACQUIRE_TOKEN: AcquireToken,
            DaemonTaskType.SYNC_USERS: SyncUsers,
            DaemonTaskType.SYNC_LEAVES: SyncLeaves, # IN PLACE OF LEAVE_CONFIRMED
            DaemonTaskType.SEND_REPORT: SendReport,
        } # IMPT to add more, need to update content template builder in Twilio, or can use 

        is_daily_update = DaemonTaskType.SEND_REPORT in tasks_to_run
        send_health_status = is_daily_update

        for i, task_type in enumerate(tasks_map.keys(), 1):

            cv_index = 1 + (i - 1) * 3 # arithmetic progression

            latest_task = None
            latest_successful_task = None

            try:
                task_body = None
                if task_type in tasks_to_run:
                    previous_task = DaemonTask.get_latest_tasks(task_type=task_type, count=1)

                    task_class = tasks_map.get(DaemonTaskType(task_type))
                    # TODO catch errors?
                    latest_task = task_class(self.job_no)
                    try:
                        latest_task.run()
                        task_body = latest_task.body
                    except Exception:
                        task_body = latest_task.body if hasattr(latest_task, 'body') else latest_task.get_err_body()

                    send_health_status = send_health_status or previous_task.status != latest_task.status

                else:
                    tasks = DaemonTask.get_latest_tasks(task_type=task_type)

                    latest_task = tasks[0] if len(tasks) > 0 else None
                    previous_task = tasks[1] if len(tasks) > 1 else None

                    # Condition to check if there is a task and to update the status conditionally
                    if latest_task:
                        task_body = 'Process is up' if latest_task.status == Status.COMPLETED else 'Process is down (see past logs)'
                        if latest_task.status == Status.COMPLETED:
                            latest_successful_task = latest_task
                    else:
                        task_body = 'Process not ran before'

                if send_health_status:
                    # If the current task is not completed, look further back if needed
                    if latest_task and latest_task.status == Status.COMPLETED:
                        latest_successful_task = latest_task
                    elif previous_task and previous_task.status == Status.COMPLETED:
                        latest_successful_task = previous_task
                    else:
                        latest_successful_task = DaemonTask.get_latest_completed_task(task_type=task_type)

                    self.cv[str(cv_index)] = task_body
                    self.cv[str(cv_index + 1)] = "NIL" if not latest_task else convert_utc_to_sg_tz(latest_task.created_at, '%d-%m-%Y %H:%M:%S')
                    self.cv[str(cv_index + 2)] = "NIL" if not latest_successful_task else convert_utc_to_sg_tz(latest_successful_task.created_at, '%d-%m-%Y %H:%M:%S')

            except Exception as e:
                self.logger.error(traceback.format_exc())
                self.cv[str(cv_index)] = "Unknown Error when sending message"
                self.cv[str(cv_index + 1)] = "Unknown Error when sending message"
                self.cv[str(cv_index + 2)] = "Unknown Error when sending message"

            message = OutgoingMessageData(
                msg_type=MessageType.SENT,
                user=self.user,
                job_no=self.job_no,
                content_sid=self.sid,
                content_variables=self.cv
            )
            MessageKnown.send_msg(message=message)

        if is_daily_update:
            self.delete_old_records()

    def delete_old_records(self):
        session = get_session()

        # Subqueries for checking references
        message_subquery = session.query(MessageKnown.job_no).filter(MessageKnown.job_no == DaemonTask.job_no).subquery()
        report_subquery = session.query(SendReport.job_no).filter(SendReport.job_no == DaemonTask.job_no).subquery()

        w_recent = window.Window.partition_by(DaemonTask.type).order_by(DaemonTask.created_at.desc())
        w_successful = window.Window.partition_by(DaemonTask.type).order_by(DaemonTask.created_at.desc())

        # Query for the most recent tasks
        most_recent_tasks_query = session.query(
            DaemonTask.job_no.label('job_no'),
            func.row_number().over(w_recent).label('rn_recent')
        ).subquery()

        # Query for the most recent successful tasks
        most_recent_successful_tasks_query = session.query(
            DaemonTask.job_no.label('job_no'),
            func.row_number().over(w_successful).label('rn_successful')
        ).filter(
            DaemonTask.status == 'COMPLETED'
        ).subquery()

        # Filter to get only the first row (most recent or successful) for each type
        filtered_most_recent = session.query(
            most_recent_tasks_query.c.job_no.label('recent_job_no'),
        ).filter(
            most_recent_tasks_query.c.rn_recent <= 2
        ).subquery()

        filtered_most_successful = session.query(
            most_recent_successful_tasks_query.c.job_no.label('successful_job_no'),
        ).filter(
            most_recent_successful_tasks_query.c.rn_successful == 1
        ).subquery()

        # Joining the two filtered results to show both recent and successful together (if needed)
        final_query = session.query(
            filtered_most_recent.c.recent_job_no,
            filtered_most_successful.c.successful_job_no
        ).subquery()

        threshold = datetime.now() - timedelta(days=180)  # temporary

        job_nos = session.query(DaemonTask.job_no).\
            filter(
                and_(
                    DaemonTask.created_at < threshold,
                    not_(exists().where(message_subquery.c.job_no == DaemonTask.job_no)),  # No reference in Message
                    not_(exists().where(final_query.c.recent_job_no == DaemonTask.job_no)),  # No reference in Metric
                    not_(exists().where(final_query.c.successful_job_no == DaemonTask.job_no)),
                    not_(exists().where(report_subquery.c.job_no == DaemonTask.job_no))  # No reference in SendReport
                )
            ).all()
        
        # Delete the jobs based on the fetched IDs
        if job_nos:
            session.query(DaemonTask).filter(DaemonTask.job_no.in_([id[0] for id in job_nos])).delete(synchronize_session=False) # This setting tells SQLAlchemy to perform the delete operation directly in the database and not to bother updating the state of the session. This is faster and less resource-intensive if you know you won’t be using the session further or if you handle session consistency manually.

        session.commit()
    


