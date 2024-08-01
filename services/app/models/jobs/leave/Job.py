from extensions import db, Session

import traceback
from sqlalchemy import desc

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.Job import Job
from models.jobs.leave.Task import TaskLeave
from models.jobs.base.constants import JobType, Status, ErrorMessage, Decision, AuthorizedDecision, OutgoingMessageData, MessageType
from models.jobs.base.utilities import is_user_status_exists

from models.jobs.leave.constants import LeaveTaskType, LeaveError, LeaveErrorMessage, LeaveType, LeaveStatus
from models.jobs.leave.utilities import print_all_dates

from models.messages.MessageKnown import MessageKnown

class JobLeave(Job):

    __tablename__ = 'job_leave'
    
    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True, nullable=False)
    error = db.Column(db.String(32), nullable=True)
    leave_type = db.Column(db.String(32), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": JobType.LEAVE,
    }

    ###########################
    # SECTION PREPROCESS
    ###########################
        
    def preprocess_msg(self, state, msg):
        '''returns the intermediate state'''
        self.logger.info(f"Enum: {msg}")

        msg_method_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            LeaveTaskType.EXTRACT_DATES: self.get_leave_selection,
            LeaveTaskType.REQUEST_CONFIRMATION: self.get_decision,
            LeaveTaskType.REQUEST_AUTHORISATION: self.get_authorisation, # IN PLACE OF LEAVE_CONFIRMED
            LeaveTaskType.APPROVE: self.get_selection_after_approval,
            LeaveTaskType.REJECT: self.get_selection_after_rejection,
            LeaveTaskType.CANCEL: self.get_selection_after_cancelled,
        }

        func = msg_method_map.get(state)
    
        if func:
            return func(msg)
        else:
            message = OutgoingMessageData(
                body=ErrorMessage.UNKNOWN_ERROR,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

    def execute(self, msg_sid):
        
        self.logger.info(f"Message SID: {msg_sid}")
        msg = Session().query(MessageKnown).get(msg_sid)
        
        try:
            if self.error:
                err_msg = self.get_error_message()
                message = OutgoingMessageData(
                    body=err_msg,
                    user_id=self.primary_user_id,
                    job_no=self.job_no
                )
                raise ReplyError(message) # no need to update the error

            last_task = Session().query(TaskLeave).filter(
                TaskLeave.job_no == self.job_no,
                TaskLeave.status != Status.FAILED
            ).order_by(
                desc(TaskLeave.created_at)
            ).first()

            if not last_task:
                task_type = LeaveTaskType.EXTRACT_DATES
            else:
                self.logger.info(f"Last task found: {last_task}")
                task_type = self.preprocess_msg(last_task.type, msg.body.upper()) # raise other replyerrors
            
            if task_type in [LeaveTaskType.APPROVE, LeaveTaskType.REJECT, LeaveTaskType.CANCEL]:

                payload = self.look_for_records(task_type)
                self.logger.info(f"Payload: {payload}")
            
                if not payload:
                    error_map = {
                        LeaveTaskType.CANCEL: LeaveErrorMessage.NO_DATES_TO_CANCEL,
                        LeaveTaskType.APPROVE: LeaveErrorMessage.NO_DATES_TO_APPROVE,
                        LeaveTaskType.REJECT: LeaveErrorMessage.NO_DATES_TO_REJECT
                    }
                    err_message = OutgoingMessageData(
                        body=error_map[task_type],
                        user_id=msg.user_id,
                        job_no=self.job_no
                    )
                    raise ReplyError(err_message, LeaveError.DATES_NOT_FOUND)
            else:
                payload = msg.body
                
            from models.jobs.leave.tasks import ExtractDates, RequestConfirmation, RequestAuthorisation, ApproveLeave, RejectLeave, CancelLeave
                    
            tasks_map = {
                LeaveTaskType.EXTRACT_DATES: [ExtractDates, RequestConfirmation],
                LeaveTaskType.REQUEST_CONFIRMATION: [RequestConfirmation],
                LeaveTaskType.REQUEST_AUTHORISATION: [RequestAuthorisation],
                LeaveTaskType.APPROVE: [ApproveLeave],
                LeaveTaskType.REJECT: [RejectLeave],
                LeaveTaskType.CANCEL: [CancelLeave]
            }

            task_classes = tasks_map.get(task_type)
            for task_class in task_classes:
                task = task_class(self.job_no, payload, msg.user_id)
                task.run()

            if not is_user_status_exists(msg.user_id): 
                return True
            
            return False
        
        except Exception as e:
            self.logger.error(traceback.format_exc())
            if isinstance(e, ReplyError):
                self.logger.info("Re raising ReplyError in Leave")
                raise
            elif isinstance(e, NoRelationsError):
                message = OutgoingMessageData(
                    user_id=msg.user_id,
                    job_no=self.job_no,
                    body=e.message or "Unknown Error: No users to forward.",
                )
                raise ReplyError(message, LeaveError.NO_USERS_TO_NOTIFY)
            else:
                message = OutgoingMessageData(
                    user_id=msg.user_id,
                    job_no=self.job_no,
                    body="Unknown Error.",
                )
                raise ReplyError(message, LeaveError.UNKNOWN)
                

    def look_for_records(self, task_type):
        status_map = {
            LeaveTaskType.CANCEL: [LeaveStatus.APPROVED, LeaveStatus.PENDING],
            LeaveTaskType.APPROVE: [LeaveStatus.PENDING],
            LeaveTaskType.REJECT: [LeaveStatus.APPROVED, LeaveStatus.PENDING]
        }

        statuses = status_map.get(task_type)

        from models.jobs.leave.LeaveRecord import LeaveRecord
        payload = LeaveRecord.get_records(self.job_no, statuses=statuses)
        return payload

    ###########################
    # HANDLING SELECTIONS
    ###########################
        

    def get_leave_selection(self, selection): # MESSAGE WHILE LEAVE_TYPE_NOT_FOUND
        print("Getting leave selection")
        if selection not in LeaveType.values():
            message = OutgoingMessageData(
                body=ErrorMessage.UNKNOWN_ERROR,
                user_id=self.primary_user_id,
                job_no=self.job_no,
            )
            raise ReplyError(message)
        return LeaveTaskType.REQUEST_CONFIRMATION
    
    def get_decision(self, selection): # MESSAGE WHILE PENDING_DECISION
        print("Getting Decision")

        if selection == Decision.CANCEL:
            message = OutgoingMessageData(
                body=LeaveErrorMessage.REGEX,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message, LeaveError.REGEX)
        
        elif selection in LeaveType.values():
            message = OutgoingMessageData(
                body=ErrorMessage.PENDING_DECISION,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

        return LeaveTaskType.REQUEST_AUTHORISATION # TODO only left Decision.CONFIRM right?
    
    def get_authorisation(self, selection): # MESSAGE WHILE PENDING_AUTHORISATION
        print("Getting authorisation")

        if selection in LeaveType.values():
            message = OutgoingMessageData(
                body=ErrorMessage.PENDING_AUTHORISATION,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

        action_map = {
            AuthorizedDecision.APPROVE: LeaveTaskType.APPROVE,
            AuthorizedDecision.REJECT: LeaveTaskType.REJECT,
            Decision.CANCEL: LeaveTaskType.CANCEL # TODO check for last confirm message? # TODO start cancel process while pending validation
        }

        return action_map.get(selection)
            
    def get_selection_after_cancelled(self, selection): # MESSAGE WHILE LEAVE_CANCELLED
        print("Handling selection after cancelled")

        if selection in AuthorizedDecision.values():
            message = OutgoingMessageData(
                body=LeaveErrorMessage.AUTHORISING_CANCELLED_MSG,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
    
        elif selection in LeaveType.values():
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_CANCELLED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    def get_selection_after_approval(self, selection): # MESSAGE WHILE LEAVE_APPROVED
        print("Handling selection after approval")

        if selection in LeaveType.values():
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_APPROVED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
        elif selection == AuthorizedDecision.APPROVE:
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_APPROVED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

        action_map = {
            AuthorizedDecision.REJECT: LeaveTaskType.REJECT,
            Decision.CANCEL: LeaveTaskType.CANCEL, # TODO check for last confirm message? # TODO start cancel process while pending validation
        }
    
        return action_map.get(selection)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    def get_selection_after_rejection(self, selection): # MESSAGE WHILE LEAVE_REJECTED
        print("Handling selection after rejection")

        if selection == AuthorizedDecision.APPROVE:
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
        
        elif selection == Decision.CANCEL:
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
    
        elif selection in LeaveType.values():
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        
    def get_error_message(status):

        message_map = {
            LeaveError.REGEX: LeaveErrorMessage.CONFIRMING_CANCELLED_MSG,
            LeaveError.TIMEOUT: LeaveErrorMessage.REQUEST_EXPIRED
        }

        return message_map.get(status, ErrorMessage.UNKNOWN_ERROR)
    
    def handle_error(self, error: LeaveError, err_message: OutgoingMessageData):

        self.error = error
        Session().commit()

        if error in [LeaveError.REGEX, LeaveError.ALL_OVERLAPPING, LeaveError.ALL_PREVIOUS_DATES, LeaveError.DURATION_MISMATCH, LeaveError.DATES_NOT_FOUND]:
            # guranteed that user_id == self.primary_user_id
            self.logger.info(f"Error message: {err_message}")
            err_message.body += " You may submit the request again."
            MessageKnown.send_msg(err_message)
        else:
        
            records = self.look_for_records(task_type=LeaveTaskType.CANCEL)

            is_primary_user = err_message.user_id == self.primary_user_id

            self.logger.info(f"is_primary_user: {is_primary_user}; records: {records}")

            # UPDATE PRIMARY USER
            if not records:
                err_message.body += f" Leave request {self.job_no} has failed. No records found for deletion."
                if is_primary_user:
                    err_message.body += " You may submit the request again."
            else:
                err_message.body += f" Leave request {self.job_no} has failed. Attempting to cancel request."
            
            # UPDATE NON PRIMARY USER
            if not is_primary_user:
                forward_msg = OutgoingMessageData( # TODO FORWARD NEED TEMPLATE
                    user_id=err_message.user_id,
                    msg_type=MessageType.FORWARD,
                    job_no=self.job_no,
                    body=err_message.body + f" {self.primary_user.alias} will be notified."
                )
                MessageKnown.send_msg(message=forward_msg)

            primary_msg = OutgoingMessageData( # TODO FORWARD NEED TEMPLATE
                user_id=self.primary_user_id,
                msg_type=MessageType.SENT,
                job_no=self.job_no,
                body=err_message.body
            )
            MessageKnown.send_msg(message=primary_msg)

            if records:
                from models.jobs.leave.tasks import CancelLeave
                task = CancelLeave(self.job_no, records, self.primary_user_id)
                task.run()
        
