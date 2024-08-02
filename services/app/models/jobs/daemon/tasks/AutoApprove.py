#### Ran at 9AM on weekdays, scans for pending leaves if RO has not approved leave.

import os
import traceback
import pandas as pd
from sqlalchemy.orm import joinedload

from extensions import Session

from models.users import User
from models.exceptions import AzureSyncError

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import current_sg_time, get_previous_weekday

from models.jobs.leave.Job import JobLeave
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_authorisation_reminder_cv

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

from models.messages.MessageKnown import MessageKnown

from routing.Scheduler import job_scheduler

class AutoApprove(TaskDaemon):

    name = "Leave Reminder"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_REMINDER
    }

    def execute(self):

        tomorrow = current_sg_time(day_offset=1).date()

        pending_leave_records = LeaveRecord.get_all_leaves(start_date=tomorrow, end_date=tomorrow, status=LeaveStatus.PENDING)
        pending_job_nos = {request.job_no for request in pending_leave_records}

        session = Session()

        for pending_job_no in pending_job_nos:

            pending_job = session.query(JobLeave).options(joinedload(JobLeave.job_no)).filter(JobLeave.job_no == pending_job_no).first()

            leave_records = [record for record in pending_leave_records if record.job_no == pending_job_no]
            if not pending_job or pending_job.error:
                for record in leave_records:
                    record.leave_status = LeaveStatus.ERROR
                session.bulk_save_objects(leave_records)
                session.commit()
                continue

            dates = list({record.date for record in leave_records})
            if len(dates) == 0:
                continue

            job_scheduler.add_to_queue(item_id=pending_job_no, payload=LeaveTaskType.APPROVE)

    def get_err_body(self) -> str:
        return "UNKNOWN"