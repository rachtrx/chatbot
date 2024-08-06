from extensions import db

from models.exceptions import ReplyError
from models.jobs.base.constants import OutgoingMessageData
from models.jobs.base.Task import Task

from models.jobs.leave.constants import LeaveTaskType, LeaveType, LeaveError
from models.jobs.base.utilities import get_latest_date_past_hour

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
        self.ro_set = self.job.primary_user.get_ro()

    def handle_dates(self):
        '''Raises Error if ALL DATES PENDING and NO ONE TO FORWARD TO'''
        if self.job.leave_type == LeaveType.MEDICAL or self.user.is_global_admin:
            self.dates_to_approve = set(self.dates_to_update)
            self.dates_to_authorise = set()
        else:
            self.dates_to_approve = {date for date in self.dates_to_update if date < get_latest_date_past_hour(weekday_offset=2)} # approve dates within 3 days
            self.dates_to_authorise = set(self.dates_to_update) - self.dates_to_approve

        self.dates_to_approve = list(self.dates_to_approve)
        self.dates_to_authorise = list(self.dates_to_authorise)

        self.logger.info(f"Dates to Approve: {self.dates_to_approve}")
        self.logger.info(f"Dates to Authorise: {self.dates_to_authorise}")

        if len(self.ro_set) == 0 and len(self.dates_to_approve) == 0:
            message = OutgoingMessageData(
                body="A reporting officer could not be found. Please inform school HR/ICT, thank you!",
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message, LeaveError.NO_USERS_TO_NOTIFY) # PERHAPS MOVE INTO ALL PENDING ONCE DONE
        