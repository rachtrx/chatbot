import os

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.constants import OutgoingMessageData, Status
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_cancel_leave_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown

class CancelLeave(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.CANCEL
    }

    def execute(self):
        # get records past 9am
        self.affected_dates = LeaveRecord.update_leaves(self.payload, LeaveStatus.CANCELLED)
        self.status = Status.COMPLETED

        reply_body = f"Leave on {print_all_dates(self.affected_dates)} have been cancelled."

        forward_metadata = None
        try:
            forward_metadata = self.get_cancel_forward_cv()
            reply_body += " Other staff will be notified."
        except NoRelationsError:
            reply_body += " No other staff were found to notify."

        if forward_metadata:
            MessageKnown.forward_template_msges(
                self.job.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user.id,
                message_context="your leave cancellation",
                **forward_metadata
            )

        reply_message = OutgoingMessageData( 
            user_id=self.user_id, 
            job_no=self.job_no, 
            body=reply_body
        )

        MessageKnown.send_msg(message=reply_message)
            
        clear_user_processing_state(self.user_id)

        return

    def get_cancel_forward_cv(self):
        # FORWARD MESSAGES
        is_approved = users_list = None

        if any(record.leave_status == LeaveStatus.APPROVED for record in self.payload):
            is_approved = True
            users_list = self.job.primary_user.get_relations(allow_null=True) # NoRelationsError raised in here.
        else:
            is_approved = False
            users_list = self.job.primary_user.get_ro()
        
        if len(users_list) == 0:
            message = OutgoingMessageData(
                body=f"Leave on {print_all_dates(self.affected_dates)} have been cancelled, but no staff were found to inform.", 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(message)
            
        else:
            cv_list = get_cancel_leave_cv( # LOOP USERS
                users_list,
                alias=self.user.alias, 
                is_approved=is_approved, 
                dates=self.affected_dates, # Don't need to mark late
            )

            return MessageKnown.construct_forward_metadata(os.getenv("LEAVE_NOTIFY_CANCEL_SID"), cv_list, users_list)