class DatesMismatchError(Exception):
    """thows error if any dates or duration are conflicting"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class AzureSyncError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)