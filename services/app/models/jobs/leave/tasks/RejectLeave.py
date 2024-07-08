import os

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

        forward_metadata = self.reject(self.payload)

        reply_message = OutgoingMessageData( 
            user_id=self.user_id, 
            job_no=self.job_no, 
            body=f"Leave on {print_all_dates(self.affected_dates)} has been rejected for {self.job.primary_user.alias} and they have been notified."
        )

        if isinstance(forward_metadata, dict): # REJECT WITH NO APPROVAL DOES NOT FORWARD
            MessageKnown.forward_template_msges(
                self.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user.id,
                message_context="your leave rejection",
                **forward_metadata
            )
            if len(zip(forward_metadata['sid_list'], forward_metadata['cv_list'], forward_metadata['users_list'])) > 0:
                reply_message.body += " Relevant staff have been notified."
            else:
                reply_message.body += " No relevant staff were found to notify. Please notify them manually."

        # Else it is none; send the normal msg
        
        MessageKnown.send_msg(message=reply_message)

        follow_up_message = OutgoingMessageData(
            msg_type=MessageType.FORWARD,
            user_id=self.job.primary_user_id,
            job_no=self.job_no,
            content_sid=os.getenv('LEAVE_FOLLOW_UP_REJECTED_SID'),
            content_variables={
                '1': self.job.primary_user.alias,
                '2': self.user.alias,
                '3': print_all_dates(self.affected_dates),
                '4': self.job_no
            }
        )
        MessageKnown.send_msg(message=follow_up_message)

        clear_user_processing_state(self.user_id)

        return

    def reject(self, records):
        self.affected_dates = [record.date for record in records]

        # FORWARD MESSAGES
        users_list = None
        if any(record.leave_status == LeaveStatus.APPROVED for record in records):
            users_list = self.job.primary_user.get_relations(ignore_users=[self.user])

        self.affected_dates = LeaveRecord.update_leaves(records, LeaveStatus.REJECTED)

        # SEND ONLY IF PREVIOUSLY APPROVED
        if not users_list: 
            return
        
        alias = self.job.primary_user.alias
        approver_alias = self.user.alias
        
        cv_list = get_reject_leave_cv( # LOOP USERS
            users_list, 
            approver_alias=approver_alias,
            dates=self.affected_dates,
            alias=alias,
        )
    
        return MessageKnown.construct_forward_metadata(os.getenv("LEAVE_NOTIFY_REJECT_SID"), cv_list, users_list)
