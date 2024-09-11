import os
import traceback
import pandas as pd
from datetime import timedelta

from models.users import User

from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.LeaveRecord import LeaveRecord

from models.jobs.leave.constants import LeaveType

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType
from models.jobs.daemon.utilities import inform_dept_admins_all_present

from models.messages.MessageKnown import MessageKnown

class SendPMReport(TaskDaemon):

    name = "Evening Report"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_PM_REPORT
    }

    def execute(self):
        
        session_order = ('AM', 'PM') # Relief?
        tmr_datetime = current_sg_time() + timedelta(days=1)
        self.date_tmr_full = tmr_datetime.strftime("%A, %d/%m/%Y")
        self.date_tmr = tmr_datetime.strftime("%d/%m/%Y")

        self.global_cv = {}

        try:
            tmr_date = tmr_datetime.date() # should send on sunday evening or no?

            leave_records = LeaveRecord.get_all_leaves(tmr_date, tmr_date)

            self.logger.info(f'leave records today: {leave_records}')

            names_list = []
            for session in session_order:
                for record in leave_records:
                    if record.dept == session:
                        names_list.append(f"{record.name} ({LeaveType.convert_attr_to_text(record.leave_type)})")
                
                dept_admins = User.get_dept_admins(session)

                reliefs = []
                err_msg = None
                if len(dept_admins) == 0:
                    reliefs.append(self.user)
                    err_msg = "No relief or HoD contacts were found"
                else:
                    for admin in dept_admins:
                        if admin.name == f'{session} Relief':
                            reliefs.append(admin)
                    if len(reliefs) == 0:
                        reliefs = dept_admins
                        err_msg = "No relief contacts were found (please inform ICT/HR)"

                self.logger.info(f"Relief Count for Session {session}: {len(reliefs)}")

                if len(names_list) == 0:
                    # inform_dept_admins_all_present(reliefs, self.job_no, self.date_tmr_full, err_msg=err_msg, dept=session, is_evening=True)
                    MessageKnown.forward_template_msges(
                        job_no=self.job_no,
                        **MessageKnown.construct_forward_metadata(
                            sid=os.getenv("SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID"), 
                            cv_list=[{
                                '1': admin.alias,
                                '2': admin.dept,
                                '3': self.date_tmr_full,
                                '4': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected'
                            } for admin in dept_admins], 
                            users_list=dept_admins
                        )
                    )

                elif len(reliefs) > 0:
                    MessageKnown.forward_template_msges(
                        job_no=self.job_no,
                        **MessageKnown.construct_forward_metadata(
                            sid=os.getenv("SEND_MESSAGE_TO_HODS_SID"), 
                            cv_list=[{
                                '1': relief.alias,
                                '2': f'{session} session',
                                '3': f'tomorrow ({self.date_tmr_full})',
                                '4': names_list,
                                '5': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected',
                            } for relief in reliefs], 
                            users_list=reliefs
                        )
                    )
                        
        except Exception as e:
            self.logger.error(e)
            raise
    