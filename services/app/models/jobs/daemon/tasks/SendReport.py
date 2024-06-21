import os
import traceback
import pandas as pd

from models.users import User
from models.exceptions import AzureSyncError

from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.LeaveRecord import LeaveRecord

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

from models.messages.MessageKnown import MessageKnown

class SendReport(TaskDaemon):

    dept_order = ('Corporate', 'ICT', 'AP', 'Voc Ed', 'Lower Pri', 'Upper Pri', 'Secondary', 'High School', 'Relief')

    

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_REPORT
    }

    def execute(self):

        cur_datetime = current_sg_time()
        self.date_today_full = cur_datetime.strftime("%A, %d/%m/%Y")
        self.date_today = cur_datetime.strftime("%d/%m/%Y")

        self.global_cv = {}
        self.dept_cv_dict = {dept: {} for dept in self.dept_order}

        try:
            global_admins = User.get_global_admins()

            all_records_today = LeaveRecord.get_all_leaves_today()
            if len(all_records_today) == 0:
                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID"), 
                        cv_list=[{
                            '1': global_admin.alias,
                            '2': self.date_today_full
                        } for global_admin in global_admins], 
                        users_list=global_admins
                    )
                )
            else:
                self.all_records_today_df = pd.DataFrame(data = all_records_today, columns=["date", "name", "dept"])
                #groupby
                leave_today_by_dept = self.all_records_today_df.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))
                # convert to a dictionary where the dept is the key
                self.dept_aggs = leave_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()

                # generate all cvs, even if all present, in order to generate all present messages for HODs as well
                self.setup_cv()

                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.environ.get("SEND_MESSAGE_TO_LEADERS_SID"), 
                        cv_list = [{
                            **self.global_cv, 
                            '1': global_admin.alias, 
                            '2': self.date_today_full
                        } for global_admin in global_admins],
                        users_list=global_admins
                    )
                )
            
                # send to HODs
                for dept in self.dept_cv_dict.keys():

                    self.logger.info(f"Preparing to send msg for department: {dept}")
                    
                    dept_admins = User.get_dept_admins(dept)

                    if dept not in self.dept_aggs:
                        MessageKnown.forward_template_msges(
                            job_no=self.job_no,
                            **MessageKnown.construct_forward_metadata(
                                sid=os.environ.get("SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID"), 
                                cv_list=[{
                                    '1': dept_admin.alias,
                                    '2': self.date_today_full
                                } for dept_admin in dept_admins], 
                                users_list=dept_admins
                            )
                        )
                    else:
                        MessageKnown.forward_template_msges(
                            job_no=self.job_no,
                            **MessageKnown.construct_forward_metadata(
                                sid=os.environ.get("SEND_MESSAGE_TO_HODS_SID"), 
                                cv_list=[{
                                    **self.dept_cv_dict[dept],
                                    '1': dept_admin.alias,
                                    '2': self.date_today_full
                                } for dept_admin in dept_admins], 
                                users_list=dept_admins
                            )
                        )
            self.body = DaemonMessage.REPORT_SENT.value
        except AzureSyncError as e:
            self.logger.error(e)
            self.body = DaemonMessage.AZURE_CONN_FAILED.value
            raise

    def get_err_body(self) -> str:
        return DaemonMessage.REPORT_FAILED.value
    
    def setup_cv(self):

        total = 0
        count = 3

        for dept in self.dept_order:

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
