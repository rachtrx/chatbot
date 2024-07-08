from sqlalchemy.types import Enum as SQLEnum

from extensions import db

from models.jobs.base.Task import Task

from models.jobs.leave.constants import LeaveTaskType

class TaskLeave(Task):

    __tablename__ = "task_leave"

    type = db.Column(SQLEnum(LeaveTaskType), nullable=False)
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), nullable=False)
    job = db.relationship("JobLeave", backref="tasks")

    user = db.relationship("User", backref="leave_tasks")

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.NONE,
        "polymorphic_on": type,
    }