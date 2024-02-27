from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc, JSON
from constants import intents, errors, CONFIRM, CANCEL
import logging
import traceback
import json
import os

from overrides import overrides

from es.manage import search_for_document
from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUser

from logs.config import setup_logger

class JobEs(JobUser):
    __tablename__ = "job_es"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    category = db.Column(db.String(20), nullable=True)
    helpful = db.Column(db.Boolean, nullable=True)
    answered = db.Column(db.Boolean, default=False, nullable=False)

    logger = setup_logger('models.job_es')
    
    __mapper_args__ = {
        "polymorphic_identity": "job_es"
    }

    def __init__(self, name, category):
        super().__init__(name)
        self.new_monthly_dates = {}
        self.current_dates = []
        self.category = category

    @overrides
    def validate_confirm_message(self):

        decision = self.current_msg.decision

        if decision == CANCEL or decision == CONFIRM:
        # TODO CANCEL THE MC
            return
        else:
            raise ReplyError(errors['UNKNOWN_ERROR'])
        
    @overrides
    def entry_action(self):
        try:
            reply = self.get_es_reply()
            # logging.info("querying documents")
        except Exception as e:
            # logging.info(e)
            logging.error(f"An error occurred: {e}", exc_info=True)
            raise ReplyError(errors['ES_REPLY_ERROR'])

        return reply

    @overrides
    def handle_user_reply_action(self):

        decision = self.current_msg.decision

        if decision == CANCEL or decision == CONFIRM:
        # TODO CANCEL THE MC
            self.commit_helpful(decision)

            body = "Thank you for the feedback!"
            
            if decision == CANCEL:
                body += " We will try our best to improve the search :)"

            return body

    @overrides
    def check_for_complete(self):
        last_message_replied = self.all_messages_successful()
        if self.answered and last_message_replied:
            self.commit_status(OK)
            self.logger.info("job complete")

    def get_es_reply(self):

        result = search_for_document(self.current_msg.body)
        # logging.info(f"Main result: {result}")

        sid, cv = self.get_query_cv(result)

        self.answered == True
        db.session.commit()

        return sid, cv

    def commit_helpful(self, helpful):
        '''tries to update helpful record'''
        
        self.helpful = helpful
        # db.session.add(self)
        db.session.commit()

        self.logger.info(f"response was helpful: {helpful}")

        return True
    
    def get_query_cv(self, result):

        print(f"reply to query result: {result}")

        content_variables = {
                '1': self.user.name,
            }

        count = 2
        if len(result) > 0:
            for data, filename, url in result:
                content_variables[str(count)] = data
                content_variables[str(count + 1)] = f"[{filename}]({url})"
                count += 2

            content_variables[str(count)] = str(CONFIRM)
            content_variables[str(count + 1)] = str(CANCEL)

            content_variables = json.dumps(content_variables)


            return os.environ.get("SEARCH_DOCUMENTS_SID"), content_variables