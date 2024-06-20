from sqlalchemy import desc
from sqlalchemy.types import Enum as SQLEnum

from extensions import db, get_session

from models.users import User

from models.jobs.base.Task import Task
from models.jobs.base.constants import Status
from models.jobs.base.utilities import current_sg_time

from models.jobs.daemon.constants import DaemonTaskType

class DaemonTask(Task):

    __tablename__ = "daemon_task"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(SQLEnum(DaemonTaskType), nullable=False)
    job_no = db.Column(db.ForeignKey("job_daemon.job_no"), nullable=False)
    job = db.relationship("JobDaemon", backref="tasks")

    __mapper_args__ = {
        "polymorphic_on": type,
        "polymorphic_identity": DaemonTaskType.NONE,
    }

    @property
    def user(self):
        if not hasattr(self, '_user'):
            self._user = get_session().query(User).filter_by(User.name == 'ICT Hotline').first()
        return self._user # TODO
    
    @user.setter
    def user(self, value):
        self._user = value

    @classmethod
    def get_latest_tasks(cls, task_type, count=2):
        tasks = get_session().query(
                cls.created_at,
                cls.status
            ).filter(
                cls.type == task_type
            ).order_by(
                desc(cls.created_at)
            ).limit(count).all()
        
        if count == 1 and len(tasks) == 1:
            return tasks[0]

    @classmethod
    def get_latest_completed_task(cls, task_type):
        return get_session().query(
                cls.created_at
            ).filter(
                cls.type == task_type,
                cls.status == Status.COMPLETED
            ).order_by(
                desc(cls.created_at)
            ).first()

    @classmethod
    def get_metric(cls, operation):
        session = get_session()
        metric = session.query(cls).filter_by(operation=operation).first()
        if not metric:
            metric = cls(operation)
        return metric

    def set_metric_status(self, job):
        cur_time = current_sg_time()

        session = get_session()
        updates_match = self.last_successful_update == self.last_update
        self.status = job.status

        if self.status == Status.COMPLETED:
            self.last_successful_update = cur_time
            self.last_successful_job_no = job.job_no
        self.last_update = cur_time
        self.last_job_no = job.job_no
        session.commit()

        # both last update and last successful update are the same, and suddenly status not ok; or last update not last usccessful update but it didnt fail
        if updates_match and self.status != Status.COMPLETED or not updates_match and self.status != Status.FAILED:
            return True
        
        return False