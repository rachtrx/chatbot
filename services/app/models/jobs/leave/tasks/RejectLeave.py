import os

from models.exceptions import NoRelationsError

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_reject_leave_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown

class RejectLeave(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.REJECT
    }

    def execute(self):

        self.affected_dates = LeaveRecord.update_leaves(self.payload, LeaveStatus.REJECTED)
        reply_body = f"Leave on {print_all_dates(self.affected_dates)} has been rejected, notifying {self.job.primary_user.alias}"

        forward_metadata = None
        try:
            forward_metadata = self.get_reject_forward_cv()
            others_body = ". Other staff will be notified."
        except NoRelationsError:
            others_body = ". No other staff were found to notify."

        follow_up_message = OutgoingMessageData(
            msg_type=MessageType.FORWARD,
            user_id=self.job.primary_user_id,
            job_no=self.job_no,
            content_sid=os.getenv('LEAVE_FOLLOW_UP_REJECTED_SID'),
            content_variables={
                '1': self.job_no,
                '2': self.job.primary_user.alias,
                '3': self.user.alias,
                '4': print_all_dates(self.affected_dates) + others_body,
            }
        )
        MessageKnown.send_msg(message=follow_up_message)

        if forward_metadata: # REJECT WITH NO APPROVAL DOES NOT FORWARD, NO RELATIONS DOES NOT FORWARD
            MessageKnown.forward_template_msges(
                self.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user.id,
                message_context="your leave rejection",
                **forward_metadata
            )

        reply_message = OutgoingMessageData( 
            user_id=self.user_id, 
            job_no=self.job_no, 
            body=reply_body + others_body
        )
        
        MessageKnown.send_msg(message=reply_message)

        clear_user_processing_state(self.user_id)

        return

    def get_reject_forward_cv(self):

        # SEND ONLY IF PREVIOUSLY APPROVED
        if not any(record.leave_status == LeaveStatus.APPROVED for record in self.payload):
            return
        
        users_list = self.job.primary_user.get_relations(ignore_users=[self.user])
        alias = self.job.primary_user.alias
        approver_alias = self.user.alias
        
        cv_list = get_reject_leave_cv( # LOOP USERS
            users_list, 
            approver_alias=approver_alias,
            dates=self.affected_dates,
            alias=alias,
        )
    
        return MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_NOTIFY_REJECT_SID"), cv_list=cv_list, users_list=users_list)
