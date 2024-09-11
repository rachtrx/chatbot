from extensions import db, Session

import traceback
from sqlalchemy import desc

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.Job import Job
from models.jobs.leave.Task import TaskLeave
from models.jobs.base.constants import JobType, Status, ErrorMessage, Decision, OutgoingMessageData, MessageType
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

        text = msg.body.upper()
        self.logger.info(f"text: {text}")

        msg_method_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            LeaveTaskType.EXTRACT_DATES: self.get_leave_selection,
            LeaveTaskType.REQUEST_CONFIRMATION: self.get_decision,
            LeaveTaskType.CONFIRM: self.get_selection_after_confirmed,
            LeaveTaskType.CANCEL: self.get_selection_after_cancelled,
        }

        func = msg_method_map.get(state)
    
        if func:
            return func(text)
        else:
            message = OutgoingMessageData(
                body=ErrorMessage.UNKNOWN_ERROR,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)
        
    def get_last_task(self):
        return Session().query(TaskLeave).filter(
            TaskLeave.job_no == self.job_no,
            TaskLeave.status != Status.FAILED
        ).order_by(
            desc(TaskLeave.created_at)
        ).first()

    def execute(self, queue_payload):

        try:
            if self.error:
                err_msg = self.get_error_message()
                message = OutgoingMessageData(
                    body=err_msg,
                    user_id=self.primary_user_id,
                    job_no=self.job_no
                )
                raise ReplyError(message, LeaveError.RERAISE) # no need to update the error

            task_payload = user_id = None

            self.logger.info(f"Message SID: {queue_payload}")
            msg = Session().query(MessageKnown).get(queue_payload)
            user_id = msg.user_id

            last_task = self.get_last_task()

            if not last_task:
                task_type = LeaveTaskType.EXTRACT_DATES
            else:
                self.logger.info(f"Last task found: {last_task}")
                task_type = self.preprocess_msg(last_task.type, msg) # raise other replyerrors
        
            if task_type == LeaveTaskType.CANCEL:

                task_payload = self.look_for_confirmed_records()
                self.logger.info(f"Payload: {task_payload}")
            
                if task_type == LeaveTaskType.CANCEL and not task_payload: # Raise Error if User Task, Return if Daemon Task
                    err_message = OutgoingMessageData(
                        body=LeaveErrorMessage.NO_DATES_TO_CANCEL,
                        user_id=msg.user_id,
                        job_no=self.job_no
                    )
                    raise ReplyError(err_message, LeaveError.DATES_NOT_FOUND)
                
                # should not be the case that CONFIRM and existing CONFIRMED record found; Redis would have blocked new requests while pending reply and will timeout the previous request before new one is accepted...
            else:
                task_payload = msg.body
                
            from models.jobs.leave.tasks import ExtractDates, RequestConfirmation, ConfirmLeave, CancelLeave
                    
            tasks_map = {
                LeaveTaskType.EXTRACT_DATES: [ExtractDates, RequestConfirmation],
                LeaveTaskType.REQUEST_CONFIRMATION: [RequestConfirmation],
                LeaveTaskType.CONFIRM: [ConfirmLeave],
                LeaveTaskType.CANCEL: [CancelLeave]
            }

            task_classes = tasks_map.get(task_type)
            for task_class in task_classes:
                task = task_class(self.job_no, task_payload, user_id)
                task.run()

            if not user_id or is_user_status_exists(user_id): 
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
                    body=e.message or "We could not find any staff in the database related to you; please inform ICT/HR.",
                )
                raise ReplyError(message, LeaveError.NO_USERS_TO_NOTIFY)
            else:
                message = OutgoingMessageData(
                    user_id=msg.user_id,
                    job_no=self.job_no,
                    body="Unknown Error.",
                )
                raise ReplyError(message, LeaveError.UNKNOWN)

    def look_for_confirmed_records(self):
        from models.jobs.leave.LeaveRecord import LeaveRecord
        payload = LeaveRecord.get_records(self.job_no, statuses=[LeaveStatus.CONFIRMED])
        return payload

    ###########################
    # HANDLING SELECTIONS
    ###########################
        

    def get_leave_selection(self, selection): # MESSAGE WHILE LEAVE_TYPE_NOT_FOUND
        print("Getting leave selection")
        if selection not in LeaveType.get_ids():
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
        
        elif selection in LeaveType.get_ids():
            message = OutgoingMessageData(
                body=ErrorMessage.PENDING_DECISION,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

        return LeaveTaskType.CONFIRM # TODO only left Decision.CONFIRM right?
            
    def get_selection_after_cancelled(self, selection): # MESSAGE WHILE LEAVE_CANCELLED
        print("Handling selection after cancelled")
    
        message = OutgoingMessageData(
            body=LeaveErrorMessage.LEAVE_CANCELLED,
            user_id=self.primary_user_id,
            job_no=self.job_no
        )
        raise ReplyError(message)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    def get_selection_after_confirmed(self, selection): # MESSAGE WHILE LEAVE_CONFIRMED
        print("Handling selection after approval")

        if selection in LeaveType.get_ids():
            message = OutgoingMessageData(
                body=LeaveErrorMessage.LEAVE_CONFIRMED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
            raise ReplyError(message)

        action_map = {
            Decision.CANCEL: LeaveTaskType.CANCEL,
        }
    
        return action_map.get(selection)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        
    def get_error_message(status):

        message_map = {
            LeaveError.REGEX: LeaveErrorMessage.CONFIRMING_CANCELLED_MSG,
            LeaveError.TIMEOUT: LeaveErrorMessage.REQUEST_EXPIRED
        }

        return message_map.get(status, ErrorMessage.UNKNOWN_ERROR)
    
    def handle_error(self, err_message: OutgoingMessageData, error):

        self.error = error
        Session().commit()

        if error in [LeaveError.REGEX, LeaveError.ALL_OVERLAPPING, LeaveError.ALL_PREVIOUS_DATES, LeaveError.DURATION_MISMATCH, LeaveError.DATES_NOT_FOUND]:
            # guranteed that user_id == self.primary_user_id
            self.logger.info(f"Error message: {err_message}")
            err_message.body += " You may submit the request again."
            MessageKnown.send_msg(err_message)
        else:
        
            records = self.look_for_confirmed_records()

            # UPDATE PRIMARY USER
            if not records:
                err_message.body += f" Leave #{self.job_no} has failed. No records found for deletion. You may submit the request again."
            else:
                err_message.body += f" Leave #{self.job_no} has failed. Attempting to cancel request."

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
        
