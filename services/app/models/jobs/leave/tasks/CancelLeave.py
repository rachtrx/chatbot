import os

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.constants import OutgoingMessageData, MessageType
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
        # self.status = Status.COMPLETED # forgotten why this is here

        forward_metadata = None
        users_list = self.job.primary_user.get_relations(allow_none=True)
        
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
                dates=self.affected_dates, # Don't need to mark late
            )

            forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_NOTIFY_CANCEL_SID"), cv_list=cv_list, users_list=users_list)

            MessageKnown.forward_template_msges(
                self.job.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user_id,
                message_context="your leave cancellation",
                **forward_metadata
            )

        reply_message = OutgoingMessageData(
            msg_type=MessageType.SENT, 
            user_id=self.job.primary_user_id,
            job_no=self.job_no
        )
        reply_message.content_sid = os.getenv('LEAVE_FOLLOW_UP_CANCEL_SID')
        reply_message.content_variables = {
            '1': self.job_no,
            '2': print_all_dates(self.affected_dates),
        }

        MessageKnown.send_msg(message=reply_message)
            
        clear_user_processing_state(self.user_id)

        return