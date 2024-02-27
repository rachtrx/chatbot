from extensions import db

from .abstract import JobSystem
from azure.utils import generate_header

from logs.config import setup_logger

from constants import OK, FAILED

import os
import pandas as pd
import requests
from utilities import current_sg_time
from models.users import User

from azure.sheet_manager import SpreadsheetManager
from models.messages.sent import MessageForward
import traceback
from azure.utils import AzureSyncError

class JobAmReport(JobSystem):

    logger = setup_logger('az.mc.report')

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

    def validate_complete(self):
        if self.forwards_status == OK:
            messages_sent = super().validate_complete()
            if messages_sent:
                return True
        return False
    
    def generate_dept_aggs_and_sid(self, url, header):

        self.logger.info("getting depts")

        response = requests.get(url=f"{url}/rows?", headers=header)
        # self.logger.info(response.text)
        if response.status_code != 200 and not response.json()['value']:
            self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID")

        mc_arrs = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
           
        
        mc_table = pd.DataFrame(data = mc_arrs, columns=["date", "name", "dept"])
        # filter by today
        
        mc_today = mc_table.loc[mc_table['date'] == self.date_today]
        
        if len(mc_today) == 0:
            self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID")
        else:
            self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_SID")

            #groupby
            mc_today_by_dept = mc_today.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))

            # convert to a dictionary where the dept is the key
            self.dept_aggs = mc_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()
            

    def notify_mcs_cv(self):

        self.logger.info("getting cvs")

        cv_and_users_list = []

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

        self.global_admins = self.root_user.get_global_admins(include_self=True)

        for global_admin in self.global_admins:

            new_cv = cv.copy()
            new_cv['1'] = global_admin.name
            cv_and_users_list.append((new_cv, global_admin))

        return cv_and_users_list    
    
    def main(self):

        sheet_manager = SpreadsheetManager()

        try:
            self.generate_dept_aggs_and_sid(sheet_manager.table_url, sheet_manager.headers)
            cv_and_users_list = MessageForward.get_cv_and_users_list(self.notify_mcs_cv)
            MessageForward.forward_template_msges(cv_and_users_list, self)
            body = "MC Reports were retrieved successfully, pending forward statuses."
        except AzureSyncError as e:
            self.logger.info(e.message)
            body = "Error connecting to Azure. Morning MC report failed."
            self.task_status = FAILED
            # raise ReplyError("I'm sorry, something went wrong with the code, please check with ICT")
        except Exception as e:
            self.logger.info(traceback.format_exc())
            body = "Unknown Error when retrieving MC Reports."
            self.task_status = FAILED

        return body