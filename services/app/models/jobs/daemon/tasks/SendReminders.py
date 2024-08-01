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

class SendReminders(TaskDaemon):

    name = "Leave Reminder"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_REMINDER
    }

    def execute(self):

        pending_leave_records = LeaveRecord.get_all_leaves(start_date=current_sg_time(day_offset=1).date(), status=LeaveStatus.PENDING)
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

            earliest_date = min(dates)
            deadline = get_previous_weekday(earliest_date).strftime("%d/%m/%Y") + ' at 5PM'

            ro_set = pending_job.primary_user.get_ro()
            if len(ro_set) == 0:
                follow_up_message = OutgoingMessageData(
                    msg_type=MessageType.FORWARD,
                    user_id=pending_job.primary_user_id,
                    job_no=pending_job_no,
                    content_sid=os.getenv('LEAVE_REMINDER_FAILED_SID'),
                    content_variables={
                        '1': pending_job_no,
                        '2': 'acknowledgement',
                        '3': 'acknowlwedged',
                        '4': deadline,
                    }
                )

                MessageKnown.send_msg(follow_up_message)
                continue
            
            cv_list = get_authorisation_reminder_cv( # LOOP RELATIONS
                ro_set, 
                alias=pending_job.primary_user.alias, 
                leave_type=pending_job.leave_type, 
                dates=dates,
                deadline=deadline,
                mark_late=False
            )

            self.forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_AUTHORISATION_REMINDER_SID"), cv_list=cv_list, users_list=self.ro_set)

            MessageKnown.forward_template_msges(
                job_no=self.job.job_no, 
                **self.forward_metadata,
            )

        session.commit()

    def get_err_body(self) -> str:
        return "UNKNOWN"