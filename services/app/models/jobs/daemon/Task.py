from sqlalchemy import desc
from sqlalchemy.types import Enum as SQLEnum

from extensions import db, Session

from models.users import User

from models.jobs.base.Task import Task
from models.jobs.base.constants import Status
from models.jobs.base.utilities import current_sg_time

from models.jobs.daemon.constants import DaemonTaskType

class TaskDaemon(Task):

    __tablename__ = "task_daemon"

    type = db.Column(SQLEnum(DaemonTaskType), nullable=False)
    job_no = db.Column(db.ForeignKey("job_daemon.job_no"), nullable=False)
    job = db.relationship("JobDaemon", backref="tasks")

    user = db.relationship("User", backref="daemon_tasks")

    __mapper_args__ = {
        "polymorphic_on": type,
        "polymorphic_identity": DaemonTaskType.NONE,
    }

    @classmethod
    def get_latest_tasks(cls, task_type, count=2):
        cls.logger.info(f"Task type in get_latest_tasks: {task_type}")
        tasks = Session().query(
                cls.created_at,
                cls.status
            ).filter(
                cls.type == task_type
            ).order_by(
                desc(cls.created_at)
            ).limit(count).all()
        
        if count == 1 and len(tasks) == 1:
            return tasks[0]
        
        return tasks

    @classmethod
    def get_latest_completed_task(cls, task_type):
        return Session().query(
                cls.created_at
            ).filter(
                cls.status == Status.COMPLETED,
                cls.type == task_type,
            ).order_by(
                desc(cls.created_at)
            ).first()
