#### Ran at 9AM on weekdays, scans for pending leaves if RO has not approved leave.

import os
import time
import traceback
import pandas as pd
from sqlalchemy.orm import joinedload

from extensions import Session

from models.exceptions import DaemonTaskError

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.Job import JobLeave
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType


from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

from models.messages.MessageKnown import MessageKnown

class AutoApprove(TaskDaemon):

    name = "Auto Approvals"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.AUTO_APPROVE
    }

    def execute(self):
        self.logger.info("In auto approvals")

        try:
            tomorrow = current_sg_time(weekday_offset=1).date()

            pending_leave_records = LeaveRecord.get_all_leaves(start_date=tomorrow, end_date=tomorrow, status=LeaveStatus.PENDING)
            pending_job_nos = {request.job_no for request in pending_leave_records}
            pending_ids = set()

            session = Session()

            from routing.Scheduler import job_scheduler

            for pending_job_no in pending_job_nos:

                pending_job = session.query(JobLeave).get(pending_job_no)

                leave_records = [record for record in pending_leave_records if record.job_no == pending_job_no]
                if len(leave_records) == 0:
                    self.logger.info(f"No records pending Approvals for {pending_job_no}")
                    continue

                if not pending_job or pending_job.error:
                    for record in leave_records:
                        record.leave_status = LeaveStatus.ERROR
                    session.bulk_save_objects(leave_records)
                    session.commit()
                    continue

                pending_ids.update({record.id for record in leave_records})
                    
                job_scheduler.add_to_queue(item_id=pending_job_no, payload=LeaveTaskType.APPROVE)

            if len(pending_ids) == 0:
                self.body = DaemonMessage.NOTHING_TO_APPROVE
                return

            self.logger.info("Waiting for Approvals")
            time.sleep(30)

            updated_leave_records = session.query(LeaveRecord).filter(LeaveRecord.id.in_(list(pending_ids))).all()
            updated_count = sum(record.leave_status == LeaveStatus.APPROVED for record in updated_leave_records)
            unknown_count = len(pending_ids) - updated_count

            follow_up_message = OutgoingMessageData(
                msg_type=MessageType.FORWARD,
                user_id=self.job.primary_user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SEND_AUTO_APPROVE_STATUS_SID'),
                content_variables={
                    '1': self.job.primary_user.alias,
                    '2': str(len(pending_ids)),
                    '3': str(updated_count), # TODO ADD REPLY BODY??
                    '4': str(unknown_count)
                }
            )

            MessageKnown.send_msg(message=follow_up_message)

        except Exception:
            raise DaemonTaskError(DaemonMessage.UNKNOWN_ERROR)