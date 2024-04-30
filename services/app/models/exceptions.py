from constants import Intent, JobStatus
from extensions import get_session
import logging
import traceback


class DurationError(Exception):
    """thows error if any dates or duration are conflicting"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, err_message, intent=Intent.OTHERS, job_status=JobStatus.SERVER_ERROR):
        self.err_message = err_message
        super().__init__(self.err_message)
        self.intent = intent
        self.job_status = job_status

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