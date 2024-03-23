from extensions import db, get_session

from .abstract import JobSystem
from azure.utils import generate_header

from logs.config import setup_logger

from constants import OK, SERVER_ERROR

import os
import pandas as pd
import requests
from utilities import current_sg_time
from models.users import User

from models.leave_records import LeaveRecord
from models.messages.sent import MessageForward
import traceback
from azure.utils import AzureSyncError
import json

class JobAmReport(JobSystem):

    logger = setup_logger('az.leave.report')

    __tablename__ = 'job_am_report'
    job_no = db.Column(db.ForeignKey("job_system.job_no"), primary_key=True)
    forwards_status = db.Column(db.Integer, default=None, nullable=True)

    dept_order = ('Corporate', 'ICT', 'AP', 'Voc Ed', 'Lower Pri', 'Upper Pri', 'Secondary', 'High School', 'Relief')
    
    __mapper_args__ = {
        "polymorphic_identity": "job_am_report",
    }

    def __init__(self):
        super().__init__() # admin name is default
        self.header = generate_header()
        cur_datetime = current_sg_time()
        self.date_today_full = cur_datetime.strftime("%A, %d/%m/%Y")
        self.date_today = cur_datetime.strftime("%d/%m/%Y")
        self.cv_and_users_list = []

    def validate_complete(self):
        if self.forwards_status == OK:
            messages_sent = super().validate_complete()
            if messages_sent:
                return True
        return False
    
    def generate_dept_aggs_and_sid(self):

        all_records_today = LeaveRecord.get_all_leaves_today()

        if len(all_records_today) == 0:
            self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID")

        else:
            
            leave_table = pd.DataFrame(data = all_records_today, columns=["date", "name", "dept"])
            
            self.logger.info(leave_table)

            self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_SID")

            #groupby
            leave_today_by_dept = leave_table.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))

            # convert to a dictionary where the dept is the key
            self.dept_aggs = leave_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()
                

    def update_cv_and_users_list(self):

        self.logger.info("getting cvs")

        cv = {
            '2': self.date_today_full
        }

        if self.content_sid == os.environ.get("SEND_MESSAGE_TO_LEADERS_SID"):
            
            dept_aggs = self.dept_aggs
            total = 0

            count = 3
            for dept in self.dept_order:
                if dept in dept_aggs:
                    cv[str(count)] = dept_aggs[dept][1]  # names
                    cv[str(count + 1)] = str(dept_aggs[dept][0]) # number of names
                    total += dept_aggs[dept][0]
                    count += 2
                    continue

                cv[str(count)] = "NIL"
                cv[str(count + 1)] = '0'  # number of names
                count += 2

            cv['21'] = str(total)

        for global_admin in User.get_global_admins():

            new_cv = cv.copy()
            new_cv['1'] = global_admin.name
            self.cv_and_users_list.append((json.dumps(new_cv), global_admin))
    
    def main(self):

        try:
            self.generate_dept_aggs_and_sid()
            self.update_cv_and_users_list()
            self.logger.info(self.cv_and_users_list)
            MessageForward.forward_template_msges(self)

            self.reply = "Successfully sent, pending forward statuses."
        except AzureSyncError as e:
            self.logger.error(e.message)
            self.reply = "Error connecting to Azure."
            self.error = True