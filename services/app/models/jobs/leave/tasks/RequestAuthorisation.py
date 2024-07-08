import os
from datetime import datetime

from models.exceptions import ReplyError

from models.jobs.base.constants import ErrorMessage, OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, current_sg_time, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveErrorMessage, LeaveError, LeaveType, LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_approve_leave_cv, get_authorisation_cv, get_authorisation_late_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown


class RequestAuthorisation(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.REQUEST_AUTHORISATION
    }

    def restore_cache(self, data):
        if not data:
            message = OutgoingMessageData(
                body=ErrorMessage.TIMEOUT_MSG,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message, LeaveError.TIMEOUT)

        self.dates_to_update = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in data['dates'] if data.get('dates', None)]

    def handle_dates(self):

        cur_date = current_sg_time().date()

        if self.job.leave_type == LeaveType.MEDICAL or self.user.is_global_admin:
            self.dates_to_approve = set(self.dates_to_update)
            self.dates_to_authorise = set()
        else:
            self.dates_to_approve = {date for date in self.dates_to_update if date == cur_date}
            self.dates_to_authorise = set(self.dates_to_update) - self.dates_to_approve

        self.dates_to_approve = list(self.dates_to_approve)
        self.dates_to_authorise = list(self.dates_to_authorise)
    
    def execute(self): # LEAVE_TYPE_FOUND

        ro = self.user.get_ro()
        if len(ro) == 0:
            message = OutgoingMessageData(
                body=LeaveErrorMessage.NO_USERS_TO_NOTIFY,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message)

        self.handle_dates()
        
        LeaveRecord.add_leaves(self.job_no, self.dates_to_authorise)
        LeaveRecord.add_leaves(self.job_no, self.dates_to_approve, leave_status=LeaveStatus.APPROVED)

        forward_metadata = None

        reply_message = OutgoingMessageData(
            msg_type=MessageType.SENT, 
            user_id=self.user_id, 
            job_no=self.job_no
        )

        relations_list = self.user.get_relations()

        if len(self.dates_to_authorise) == 0 and len(self.dates_to_approve) == 0: # NO DATES FOUND
            message = OutgoingMessageData(
                body=ErrorMessage.DATES_NOT_FOUND,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message) # TODO

        elif len(self.dates_to_authorise) == 0 and len(self.dates_to_approve) > 0: # ALL TO APPROVE IMMEDIATELY
            cv_list = get_approve_leave_cv( # LOOP RELATIONS
                relations_list, 
                alias=self.user.alias, 
                leave_type=self.job.leave_type, 
                dates=self.dates_to_approve,
                mark_late=True
            )

            forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_NOTIFY_APPROVE_SID"), cv_list=cv_list, users_list=relations_list)

            reply_message.content_sid = os.getenv('NOTIFY_FORWARDS_SENT_APPROVED_SID')
            reply_message.content_variables = {
                '1': self.job_no,
                '2': print_all_dates(self.dates_to_approve)
            }

        else: # ALL PENDING
            authorisers_list = list(self.user.get_ro().union(self.user.get_dept_admins()))
            relations_name_list = [r.alias for r in relations_list]

            if len(self.dates_to_authorise) > 0 and len(self.dates_to_approve) == 0: # ALL DATES REQUIRE APPROVAL
                cv_list = get_authorisation_cv( # LOOP RELATIONS
                    authorisers_list, 
                    alias=self.user.alias, 
                    leave_type=self.job.leave_type, 
                    dates=self.dates_to_authorise,
                    relation_aliases=relations_name_list,
                    mark_late=True
                )

                forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_AUTHORISATION_REQUEST_SID"), cv_list=cv_list, users_list=authorisers_list)

                reply_message.content_sid = os.getenv('NOTIFY_FORWARDS_SENT_PENDING_APPROVAL_SID')
                reply_message.content_variables = {
                    '1': self.job_no,
                    '2': print_all_dates(self.dates_to_authorise)
                }

            else: # PARTIALLY APPROVED
                authorisation_cv_list = get_authorisation_late_cv( # LOOP RELATIONS
                    authorisers_list, 
                    alias=self.user.alias, 
                    leave_type=self.job.leave_type, 
                    dates_approved=self.dates_to_approve,
                    dates_to_authorise=self.dates_to_authorise,
                    relation_aliases=relations_name_list,
                    mark_late=True
                )
                authorisation_sid_list = [os.getenv("LEAVE_AUTHORISATION_REQUEST_LATE_SID")] * len(authorisation_cv_list)

                other_relations_list = self.user.get_relations(ignore_users=authorisers_list)
                notify_cv_list = get_approve_leave_cv( # LOOP RELATIONS
                    other_relations_list, 
                    alias=self.user.alias, 
                    leave_type=self.job.leave_type, 
                    dates=self.dates_to_approve,
                    mark_late=True
                )
                notify_sid_list = [os.getenv("LEAVE_NOTIFY_APPROVE_SID")] * len(notify_cv_list)

                forward_metadata = MessageKnown.construct_forward_metadata(
                    sid=[*authorisation_sid_list, *notify_sid_list], 
                    cv_list=[*authorisation_cv_list, *notify_cv_list], 
                    users_list=[*authorisers_list, *other_relations_list]
                )

                reply_message.content_sid = os.getenv('NOTIFY_FORWARDS_SENT_PARTIAL_APPROVED_SID')
                reply_message.content_variables = {
                    '1': self.job_no,
                    '2': print_all_dates(self.dates_to_approve),
                    '3': print_all_dates(self.dates_to_authorise)
                }

        MessageKnown.send_msg(message=reply_message)
        
        MessageKnown.forward_template_msges(
            job_no=self.job.job_no, 
            callback=self.forwards_callback,
            user_id_to_update=self.user_id,
            message_context=f"your leave / leave request with Ref No. {self.job_no}",
            **forward_metadata,
        )

        # SET USER TO COMPLETED
        clear_user_processing_state(self.user_id)

        return