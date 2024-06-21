from sqlalchemy.types import Enum as SQLEnum

from extensions import db

from models.jobs.base.Task import Task

from models.jobs.leave.constants import LeaveTaskType

class TaskLeave(Task):

    __tablename__ = "task_leave"

    job_no = db.Column(db.ForeignKey("job_leave.job_no"), primary_key=True, nullable=False)
    id = db.Column(db.String(32), nullable=False)
    type = db.Column(SQLEnum(LeaveTaskType), nullable=False)
    job = db.relationship("JobLeave", backref="tasks")

    user_id = db.Column(db.ForeignKey("users.id"), nullable=True)
    user = db.relationship("User", backref="tasks")

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.NONE,
        "polymorphic_on": type,
    }