import os

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import LeaveTask
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_cancel_leave_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown

class CancelLeave(LeaveTask):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.CANCEL
    }

    def execute(self):
        # get records past 9am
        forward_metadata = self.cancel(self.payload)

        reply_message = OutgoingMessageData( 
            msg_type=MessageType.SENT, 
            user=self.user.alias, 
            job_no=self.job_no, 
            body=f"Leave on {print_all_dates(self.affected_dates)} has been cancelled, relevant staff have been notified."
        )

        MessageKnown.send_msg(message=reply_message)

        MessageKnown.forward_template_msges(
            self.job.job_no,
            callback=self.forwards_callback,
            user_id_to_update=self.job.user.id,
            message_context="your leave cancellation",
            **forward_metadata
        )

        clear_user_processing_state(self.user_id)

        return

    def cancel(self, records):
        # FORWARD MESSAGES
        is_approved = users_list = None

        if any(record.status == LeaveStatus.APPROVED for record in records):
            is_approved = True
            users_list = self.job.user.get_relations()
        else:
            is_approved = False
            users_list = list(self.user.get_ro().union(self.user.get_dept_admins()))

        self.affected_dates = LeaveRecord.update_leaves(records, LeaveStatus.CANCELLED)
            
        cv_list = get_cancel_leave_cv( # LOOP USERS
            users_list,
            alias=self.user.alias, 
            is_approved=is_approved, 
            dates=self.affected_dates, # Don't need to mark late
        )

        return MessageKnown.construct_forward_metadata(os.environ.get("LEAVE_NOTIFY_CANCEL_SID"), cv_list, users_list)