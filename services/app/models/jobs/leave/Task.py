from extensions import db

from models.exceptions import ReplyError
from models.jobs.base.constants import OutgoingMessageData
from models.jobs.base.Task import Task

from models.jobs.leave.constants import LeaveTaskType

class TaskLeave(Task):

    __tablename__ = "task_leave"

    type = db.Column(db.String(length=32), nullable=False)
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), nullable=False)
    job = db.relationship("JobLeave", backref="tasks")

    user = db.relationship("User", backref="leave_tasks")

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.NONE,
        "polymorphic_on": type,
    }

    def setup_other_users(self):
        self.relations_set = self.job.primary_user.get_relations() # raise error if none # PERHAPS MOVE INTO ALL PENDING ONCE IF TIGERNIX INTEGRATES