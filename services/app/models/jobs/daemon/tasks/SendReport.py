import os
import traceback
import pandas as pd

from models.users import User
from models.exceptions import AzureSyncError, DaemonTaskError

from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.LeaveRecord import LeaveRecord

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage

from models.messages.MessageKnown import MessageKnown

class SendReport(TaskDaemon):

    name = "Morning Report"

    dept_order = ('Corporate', 'ICT', 'AP', 'Voc Ed', 'AM', 'PM') # Relief?

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_REPORT
    }

    def execute(self):

        cur_datetime = current_sg_time()
        self.date_today_full = cur_datetime.strftime("%A, %d/%m/%Y")
        self.date_today = cur_datetime.strftime("%d/%m/%Y")

        self.global_cv = {}

        try:

            global_admins = User.get_global_admins()
            if len(global_admins) == 0:
                return # TODO, inform primary user?

            today_date = current_sg_time().date()

            leave_records = LeaveRecord.get_all_leaves(today_date, today_date)

            self.logger.info(f'leave records today: {leave_records}')

            all_records_today = [
                {
                    "date": record.date,
                    "name": f"{record.name} ({record.leave_type})",
                    "dept": record.dept
                }
                for record in leave_records
            ]

            if len(all_records_today) == 0:
                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.getenv("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID"), 
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
                self.send_to_hods()

                
                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.getenv("SEND_MESSAGE_TO_LEADERS_SID"), 
                        cv_list = [{
                            **self.global_cv, 
                            '1': global_admin.alias, 
                            '2': self.date_today_full
                        } for global_admin in global_admins],
                        users_list=global_admins
                    )
                )
                        
        except AzureSyncError as e:
            self.logger.error(e)
            raise DaemonTaskError(DaemonMessage.AZURE_CONN_FAILED)
    
    def send_to_hods(self):

        total = 0

        for i, dept in enumerate(self.dept_order, 3):

            dept_admins = User.get_dept_admins_for_dept(dept)

            if dept in self.dept_aggs:

                name_list = self.dept_aggs[dept][1]  # names
                dept_total = self.dept_aggs[dept][0] # number of names
                
                # update the global 
                self.global_cv[str(i)] = f" ({str(dept_total)}): {name_list}"
                total += dept_total

                if len(dept_admins) == 0:
                    continue

                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.getenv("SEND_MESSAGE_TO_HODS_SID"), 
                        cv_list=[{
                            '1': dept_admin.alias,
                            '2': dept,
                            '3': self.date_today_full,
                            '4': name_list,
                        } for dept_admin in dept_admins], 
                        users_list=dept_admins
                    )
                )
            else:
                self.global_cv[str(i)] = f" (0): NIL" # for global

                if len(dept_admins) == 0:
                    continue

                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.getenv("SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID"), 
                        cv_list=[{
                            '1': dept_admin.alias,
                            '2': self.date_today_full
                        } for dept_admin in dept_admins], 
                        users_list=dept_admins
                    )
                )

        self.global_cv['9'] = str(total)

        return
