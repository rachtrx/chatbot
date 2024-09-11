import os
import traceback
import pandas as pd

from models.users import User
from models.exceptions import AzureSyncError, DaemonTaskError

from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.LeaveRecord import LeaveRecord

from models.jobs.leave.constants import LeaveType

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType
from models.jobs.daemon.utilities import inform_dept_admins_all_present

from models.messages.MessageKnown import MessageKnown

class SendAMReport(TaskDaemon):

    name = "Morning Report"

    dept_order = ('Corporate', 'ICT', 'AP', 'Voc Ed', 'AM', 'PM') # Relief not for now due to HR workload?

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_AM_REPORT
    }

    def execute(self):

        cur_datetime = current_sg_time()
        self.date_today_full = cur_datetime.strftime("%A, %d/%m/%Y")
        self.date_today = cur_datetime.strftime("%d/%m/%Y")

        self.global_cv = {}

        try:
            global_admins = User.get_global_admins()
            dept_admins = User.get_dept_admins(dept=None)
            err_msg = None
            if len(global_admins) == 0 and len(dept_admins) == 0:
                return # TODO, inform primary user?
            # elif len(dept_admins) == 0:
            #     err_msg = "No HoDs were found."

            today_date = cur_datetime.date()

            leave_records = LeaveRecord.get_all_leaves(today_date, today_date)

            self.logger.info(f'leave records today: {leave_records}')

            all_records_today = [
                {
                    "date": record.date,
                    "name": f"{record.name} ({LeaveType.convert_attr_to_text(record.leave_type)})",
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
                            '1': admin.alias,
                            '2': self.date_today_full,
                            '3': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected'
                        } for admin in global_admins], 
                        users_list=global_admins
                    )
                )
                # inform_dept_admins_all_present(dept_admins, self.job_no, self.date_today_full)
                MessageKnown.forward_template_msges(
                    job_no=self.job_no,
                    **MessageKnown.construct_forward_metadata(
                        sid=os.getenv("SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID"), 
                        cv_list=[{
                            '1': admin.alias,
                            '2': admin.dept,
                            '3': self.date_today_full,
                            '4': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected'
                        } for admin in dept_admins], 
                        users_list=dept_admins
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
                            '1': f'Morning {global_admin.alias}', 
                            '2': self.date_today_full
                        } for global_admin in global_admins],
                        users_list=global_admins
                    )
                )
                        
        except Exception as e:
            self.logger.error(e)
            raise
    
    def send_to_hods(self):

        total = 0

        for i, dept in enumerate(self.dept_order, 3):

            dept_admins = User.get_dept_admins(dept)

            err_msg = None

            if dept in ['AM', 'PM'] and not any(admin.name == f'{dept} Relief' for admin in dept_admins):
                err_msg = "No relief contacts were found (please inform ICT/HR)"

            if dept in self.dept_aggs:

                name_list = self.dept_aggs[dept][1]  # names
                dept_total = self.dept_aggs[dept][0] # number of names
                
                # update the global 
                self.global_cv[str(i)] = f" ({str(dept_total)}): {name_list}"
                total += dept_total

                if len(dept_admins) > 0:
                    MessageKnown.forward_template_msges(
                        job_no=self.job_no,
                        **MessageKnown.construct_forward_metadata(
                            sid=os.getenv("SEND_MESSAGE_TO_HODS_SID"), 
                            cv_list=[{
                                '1': f'Morning {dept_admin.alias}',
                                '2': dept,
                                '3': f'today ({self.date_today_full})',
                                '4': name_list,
                                '5': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected'
                            } for dept_admin in dept_admins], 
                            users_list=dept_admins
                        )
                    )
            else:
                self.global_cv[str(i)] = f" (0): NIL" # for global

                if len(dept_admins) > 0:
                    inform_dept_admins_all_present(dept_admins, self.job_no, self.date_today_full, err_msg=err_msg, dept=dept)

            if err_msg and len(dept_admins) == 0:
                self.global_cv[str(i)] = f'{self.global_cv[str(i)]}. "No relief or HoD contacts were found (please inform ICT/HR)'
        
        self.global_cv['9'] = str(total)

        return

    