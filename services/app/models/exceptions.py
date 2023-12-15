from constants import intents, FAILED

# class DatesMismatchError(Exception):
#     """thows error if any dates or duration are conflicting"""

#     def __init__(self, message):
#         self.message = message
#         super().__init__(self.message)

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, err_message, intent=intents['OTHERS'], job_status=FAILED, new_message=None):
        self.err_message = err_message
        super().__init__(self.err_message)
        self.intent = intent
        self.job_status = job_status
        self.new_message = new_message

class AzureSyncError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)