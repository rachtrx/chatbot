from extensions import db, get_session

from .abstract import JobSystem
from azure.utils import generate_header

from MessageLogger import setup_logger

from constants import JobStatus
from sqlalchemy.types import Enum as SQLEnum

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
        
        # for each individual forward message list
        self.cv_and_users_list = []
        
        # for different CVs
        self.dept_cv_dict = {}
        self.global_cv = {}

    def validate_complete(self):
        messages_sent = super().validate_complete()
        if messages_sent:
            return True
        return False
    
    def generate_all_cv(self):

        base_cv = {
            '2': self.date_today_full
        }

        # init global cv
        self.global_cv = base_cv.copy()
        total = 0
        count = 3

        for dept in self.dept_order:

            # init dept cv
            self.dept_cv_dict[dept] = base_cv.copy()

            if dept in self.dept_aggs:
                # update the global 
                self.global_cv[str(count)] = self.dept_aggs[dept][1]  # names
                self.global_cv[str(count + 1)] = str(self.dept_aggs[dept][0]) # number of names
                total += self.dept_aggs[dept][0]

                # update the dept
                self.dept_cv_dict[dept]['3'] = dept
                self.dept_cv_dict[dept]['4'] = self.dept_aggs[dept][1]
            else:
                # update the global
                self.global_cv[str(count)] = "NIL"
                self.global_cv[str(count + 1)] = '0' # number of names

                # update the dept
                self.dept_cv_dict[dept]['3'] = dept
                
            # update global counter
            count += 2

        self.global_cv['21'] = str(total)

        return
    
    def update_cv_global(self):

        for global_admin in User.get_global_admins():
            new_cv = self.global_cv.copy()
            new_cv['1'] = global_admin.alias
            self.cv_and_users_list.append((json.dumps(new_cv), global_admin))

    def update_cv_dept(self, dept):
        self.cv_and_users_list = []
        self.logger.info(f"cv and users list after reset: {self.cv_and_users_list}")

        for dept_admin in User.get_dept_admins(dept):
            new_cv = self.dept_cv_dict[dept].copy()
            new_cv['1'] = dept_admin.alias
            self.cv_and_users_list.append((json.dumps(new_cv), dept_admin))

        self.logger.info(f"cv and users list after looping admins: {self.cv_and_users_list}, length {len(self.cv_and_users_list)}")
        
        if len(self.cv_and_users_list) > 0:
            self.logger.info(f"Department: {dept}")
            self.logger.info(f"cv and users list: {self.cv_and_users_list}")
    
    def main(self):

        try:
            all_records_today = LeaveRecord.get_all_leaves_today()
            if len(all_records_today) == 0:
                self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID")
                self.dept_aggs = {}
            else:
                self.content_sid = os.environ.get("SEND_MESSAGE_TO_LEADERS_SID")
                self.all_records_today_df = pd.DataFrame(data = all_records_today, columns=["date", "name", "dept"])
                #groupby
                leave_today_by_dept = self.all_records_today_df.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))
                # convert to a dictionary where the dept is the key
                self.dept_aggs = leave_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()

            # generate all cvs, even if all present, in order to generate all present messages for HODs as well
            self.generate_all_cv()

            # send to leaders
            self.update_cv_global()
            MessageForward.forward_template_msges(self)
            
            self.logger.info(self.cv_and_users_list)
            
            # send to HODs
            for dept in self.dept_cv_dict.keys():
                if dept not in self.dept_aggs:
                    self.content_sid = os.environ.get('SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID')
                else:
                    self.content_sid = os.environ.get('SEND_MESSAGE_TO_HODS_SID')
                self.update_cv_dept(dept)
                self.logger.info(f"Preparing to send msg for department: {dept}")
                MessageForward.forward_template_msges(self)

            self.reply = "Successfully sent, pending forward statuses."
        except AzureSyncError as e:
            self.logger.error(e.message)
            self.reply = "Error connecting to Azure."
            self.error = True