import os
from datetime import datetime, timedelta
from sqlalchemy import func, not_, exists, and_, select
from sqlalchemy.sql import func, over

from extensions import Session, db

from models.jobs.daemon.Task import TaskDaemon

from models.messages.MessageKnown import MessageKnown
from models.jobs.daemon.tasks import SendReport

from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

class CleanTasks(TaskDaemon):
    name = "Clean Tasks"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.CLEAN_TASKS
    }

    def execute(self):
        session = Session()

        # Subqueries for checking references
        message_subquery = session.query(MessageKnown.job_no).filter(MessageKnown.job_no == TaskDaemon.job_no).subquery()
        report_subquery = session.query(SendReport.job_no).filter(SendReport.job_no == TaskDaemon.job_no).subquery()

        # Define queries to capture row numbers first
        recent_tasks_with_row_numbers = select(
            TaskDaemon.job_no.label('recent_job_no'),
            func.row_number().over(
                order_by=TaskDaemon.created_at.desc(),
                partition_by=TaskDaemon.type
            ).label('rn_recent')
        ).subquery()

        successful_tasks_with_row_numbers = select(
            TaskDaemon.job_no.label('successful_job_no'),
            func.row_number().over(
                order_by=TaskDaemon.created_at.desc(),
                partition_by=TaskDaemon.type
            ).label('rn_successful')
        ).where(
            TaskDaemon.status == 'COMPLETED'
        ).subquery()

        # Filtering to get the most recent task and the most recent successful task
        most_recent_tasks_query = select(
            recent_tasks_with_row_numbers.c.recent_job_no
        ).where(
            recent_tasks_with_row_numbers.c.rn_recent == 1
        ).subquery()

        most_recent_successful_task_query = select(
            successful_tasks_with_row_numbers.c.successful_job_no
        ).where(
            successful_tasks_with_row_numbers.c.rn_successful == 1
        ).subquery()

        # Joining the two filtered results to show both recent and successful together
        combined_query = select(
            most_recent_tasks_query.c.recent_job_no.label('job_no')
        ).union(
            select(
                most_recent_successful_task_query.c.successful_job_no.label('job_no')
            )
        ).subquery()

        threshold = datetime.now() - timedelta(days=180)  # temporary

        job_nos = session.query(TaskDaemon.job_no).\
            filter(
                and_(
                    TaskDaemon.created_at < threshold,
                    not_(exists().where(message_subquery.c.job_no == TaskDaemon.job_no)),  # No reference in Message
                    not_(exists().where(combined_query.c.job_no == TaskDaemon.job_no)),
                    not_(exists().where(report_subquery.c.job_no == TaskDaemon.job_no))  # No reference in SendReport
                )
            ).all()
        
        # why [id[0] for id in job_nos]?
        # results = session.query(TaskDaemon).all() returns a list of TaskDaemon objects
        # session.query(TaskDaemon.job_no).all() returns a list of tuples
        
        # Delete the jobs based on the fetched IDs
        if job_nos:
            session.query(TaskDaemon).filter(TaskDaemon.job_no.in_([id[0] for id in job_nos])).delete(synchronize_session=False) # This setting tells SQLAlchemy to perform the delete operation directly in the database and not to bother updating the state of the session. This is faster and less resource-intensive if you know you won’t be using the session further or if you handle session consistency manually.

        session.commit()