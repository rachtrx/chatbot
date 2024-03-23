from constants import intents, SERVER_ERROR, OK
from extensions import get_session
from constants import messages
import logging
import traceback


class DurationError(Exception):
    """thows error if any dates or duration are conflicting"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, err_message, intent=intents['OTHERS'], job_status=SERVER_ERROR):
        self.err_message = err_message
        super().__init__(self.err_message)
        self.intent = intent
        self.job_status = job_status

    def send_error_msg(self, sid, user_str, user_or_no):
        from models.jobs.user.abstract import JobUser
        from models.jobs.unknown.unknown import JobUnknown
        from models.jobs.abstract import Job
        from models.messages.abstract import Message
        from models.messages.received import MessageReceived
        from models.users import User

        try:
            session = get_session()

            received_message = session.query(MessageReceived).filter_by(sid=sid).first()
                
            if received_message:    
                job = received_message.job
                number = job.user.sg_number
            else:
                if isinstance(user_or_no, User):
                    name = user_or_no.name
                    number = user_or_no.sg_number
                    job = JobUser.create_job(self.intent, user_str, name)
                else:
                    number = user_or_no
                    logging.info(f"unknown number: {number}")
                    prev_job = JobUnknown.check_for_prev_job(user_or_no)
                    if prev_job:
                        return
                    job = JobUnknown(number)
                
                received_message = Message.create_message(messages['RECEIVED'], job.job_no, sid, user_str)

            job.commit_status(self.job_status)

            logging.info(f"status after replyError: {job.status}")
            
            job2 = session.query(Job).filter_by(job_no=job.job_no).first()
            logging.info(f"Status in database: {job2.status}")
            logging.info(f"Session id in workflow: {id(session)}")

            # check_obj_state(job) # imported from utilities

            received_message.reply = self.err_message
            sent_msg = received_message.create_reply_msg()
            return sent_msg
        
        except Exception:
            logging.error("reply error exception")
            logging.error(traceback.format_exc())
            if job and not getattr(job, "local_db_updated", None) and not job.status == OK:
                job.commit_status(SERVER_ERROR)

class AzureSyncError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

def handle_value_error(ex):
    logging.error("ValueError encountered.")

def handle_key_error(ex):
    logging.error("KeyError encountered.")

def handle_default(ex):
    logging.error(f"Unexpected error: {ex}")

exception_handlers = {
    ValueError: handle_value_error,
    KeyError: handle_key_error,
}