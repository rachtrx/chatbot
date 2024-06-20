import os
import json
import traceback
import requests
import pandas as pd

from datetime import datetime, timedelta
from sqlalchemy import select, func, extract, cast, Integer

from extensions import get_session

from models.users import User

from models.exceptions import AzureSyncError

from models.jobs.base.utilities import current_sg_time, print_all_dates
from models.jobs.base.constants import Status

from models.jobs.daemon.Task import DaemonTask
from models.jobs.daemon.SpreadsheetManager import SpreadsheetManager
from models.jobs.daemon.utilities import generate_header
from models.jobs.daemon.constants import Update, Link, DaemonMessage, DaemonTaskType

from models.jobs.leave.constants import LeaveStatus
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.Job import JobLeave

from models.messages.MessageKnown import MessageKnown

class SyncLeaves(DaemonTask):

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SYNC_LEAVES
    }

    def get_err_body(self) -> str:
        
        return DaemonMessage.SYNC_FAILED.value + self.unmatched_records_body if self.unmatched_records_body else ""

    def execute(self):

        self.start_time = current_sg_time()
        self.latest_date = self.start_time.date() - timedelta(days=1)

        self.records = {
            Update.ADD: {Status.FAILED: {}, Status.COMPLETED: {}},
            Update.DEL: {Status.FAILED: {}, Status.COMPLETED: {}}
        }

        session = get_session()

        az_mmyy_arr = self.loop_leave_files(latest_date=self.latest_date)
        # self.logger.info(az_mmyy_arr)
        db_mmyy_arr = self.get_all_mmyy_in_db()
        # self.logger.info(db_mmyy_arr)

        combined_mmyy_set = set(az_mmyy_arr) | set(db_mmyy_arr)

        # self.logger.info(f"Combined list: {combined_mmyy_list}")

        all_missing_job_names = {}

        for mm, yy in combined_mmyy_set: # contains the mm, yy that are >= ysterday

            # self.logger.info(f"month: {mm}, year: {yy}")

            cur_manager = SpreadsheetManager(mmyy=[mm, yy])

            # get azure df
            cur_az_df = self.get_az_df(cur_manager)

            # get db df, including cancelled records
            cur_db_df = self.get_db_df(mm, yy)

            # dates_to_del: in az, not in db. dates_to_update: in db, not in az
            combined_df = pd.merge(cur_az_df, cur_db_df, how="outer", indicator=True)
            combined_df['_merge'] = combined_df['_merge'].replace({'left_only': 'az_only', 'right_only': 'db_only'})

            self.logger.info("Printing combined df")
            self.logger.info(combined_df)
            self.logger.info(combined_df.dtypes)

            if combined_df.empty:
                self.body = DaemonMessage.NOTHING_TO_SYNC.value
                return # TODO
            
            # FIND ANY UNUPDATED RECORDS
            completed_ids = combined_df.loc[((combined_df._merge == "both") & (combined_df.leave_status == LeaveStatus.APPROVED)) & (~combined_df.sync_status == Status.COMPLETED), "record_id"]
            if not completed_ids.empty:
                session.bulk_update_mappings(LeaveRecord, [
                    {'id': completed_id, 'sync_status': Status.COMPLETED }
                    for completed_id in completed_ids
                ])

            # both but cancelled or az only (no record ever made in local db) means have to del from Sharepoint
            combined_df.loc[((combined_df._merge == "both") & (~combined_df.leave_status == LeaveStatus.APPROVED) | (combined_df._merge == "az_only")), "action"] = Update.DEL
            # PASS: both and not cancelled means updated on both sides
            # db only and not cancelled means need to add to Sharepoint
            combined_df.loc[((combined_df._merge == "db_only") & (combined_df.leave_status == LeaveStatus.APPROVED)), "action"] = Update.ADD
            # PASS: right only and cancelled means updated on both sides

            dates_to_del = combined_df.loc[combined_df.action == Update.DEL].copy()
            dates_to_update = combined_df.loc[combined_df.action == Update.ADD].copy()

            # self.logger.info("Printing dates to del and add")
            # self.logger.info(dates_to_del)
            # self.logger.info(dates_to_update)
            self.logger.info(f"length of data to del: {dates_to_del.shape}")
            self.logger.info(f"length of data to add: {dates_to_update.shape}")

            if dates_to_del.empty and dates_to_update.empty:
                self.body = DaemonMessage.NOTHING_TO_SYNC.value
                return # TODO
            
            del_status = add_status = Status.COMPLETED
            
            if not dates_to_del.empty:
                # delete from excel
                indexes_to_rm = dates_to_del["az_index"].dropna().astype(int).tolist()
                self.logger.info(f"indexes to remove: {indexes_to_rm}")

                # cancel MCs
                try:
                    self.cur_manager.delete_from_excel(indexes_to_rm)
                except AzureSyncError as e:
                    del_status = Status.FAILED
                    self.logger.error(e)
                
                del_grouped = dates_to_del.groupby(['_merge', 'name'], observed=True)
                for (_merge, name), group in del_grouped:
                    del_dates = [date for date in group['date'] if not pd.isna(date)]
                    if _merge == "az_only": # blank row / no match with db. if no match and name: send a spearate message
                        if name and not pd.isna(name) and len(del_dates) > 0:
                            self.logger.info(f"Name added: {name}")
                            if name not in all_missing_job_names:
                                all_missing_job_names[name] = []
                            all_missing_job_names[name].extend(del_dates)
                        continue
                    
                    record_ids = group['record_id'].tolist()

                    records = session.query(
                        LeaveRecord.id, 
                        LeaveRecord.date
                    ).filter(
                        LeaveRecord.id.in_(record_ids),
                        LeaveRecord.sync_status != del_status # TODO should users be informed twice?
                    ).all()

                    update_data = [{'id': record.id, 'sync_status': del_status} for record in records]

                    session.bulk_update_mappings(LeaveRecord, update_data)

                    for record in records:
                        self.update_records(Update.DEL, del_status, name, record.date)
            
            if not dates_to_update.empty:
                data_to_add = list(dates_to_update.apply(self.format_row, axis=1))
                try:
                    self.cur_manager.upload_data(data_to_add)
                except AzureSyncError as e:
                    add_status = Status.FAILED
                    self.logger.error(e)

                add_grouped = dates_to_update.groupby(['_merge', 'name'], observed=True)
                for (_merge, name), group in add_grouped:

                    record_ids = group['record_id'].tolist()

                    records = session.query(
                        LeaveRecord.id,
                        LeaveRecord.date
                    ).filter(
                        LeaveRecord.id.in_(record_ids),
                        LeaveRecord.sync_status != add_status # TODO should users be informed twice?
                    ).all()

                    update_data = [{'id': record.id, 'sync_status': add_status} for record in records]

                    session.bulk_update_mappings(LeaveRecord, update_data)

                    for record in records:
                        self.update_records(Update.ADD, add_status, name, record.date)

        if len(self.records) > 0:
            self.logger.info("sending messages")
            self.logger.info(f"records of new leaves: {self.records}")
        
            MessageKnown.forward_template_msges(
                self.job.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.user.id,
                message_context='their updating of leaves',
                **self.get_forward_metadata()
            )

        self.unmatched_records_body = None
        if len(all_missing_job_names) > 0:
            unmatched_records = '; '.join(f"{name}: {print_all_dates(date_list, date_obj=True)}" for name, date_list in all_missing_job_names.items())
            self.unmatched_records_body += f". Also, unmatched records were found in Azure: {unmatched_records}"

        if add_status == Status.FAILED or del_status == Status.FAILED:
            self.body = DaemonMessage.AZURE_CONN_FAILED.value + self.unmatched_records_body if self.unmatched_records_body else ""
            raise Exception
        else:
            self.body = DaemonMessage.SYNC_COMPLETED.value + self.unmatched_records_body if self.unmatched_records_body else ""

    def loop_leave_files(self, leave_files_url = Link.LEAVE_FILES_URL, latest_date=None):

        header = generate_header()

        response = requests.get(url=leave_files_url, headers=header)

        # response.raise_for_status()
        if not 200 <= response.status_code < 300:
            self.logger.info("something went wrong when getting files")
            self.logger.info(response.text)
            raise AzureSyncError("Connection to Azure failed")
        
        months = []

        for value in response.json()['value']:
            if value['name'].endswith(".xlsx"):
                year = value['name'].split('.')[0]
                year_int = int(year)
                current_year = current_sg_time().year

                if not year_int < current_year: # file is from previous years

                    new_url = Link.DRIVE_URL + value['id'] + '/workbook/worksheets'
                    self.logger.info(f"getting worksheets: {new_url}")
                    sheets_resp = requests.get(url=new_url, headers=header)

                    if not 200 <= sheets_resp.status_code < 300:
                        self.logger.info("something went wrong when getting sheets")
                        raise AzureSyncError("Connection to Azure failed")
                    
                    for obj in sheets_resp.json()['value']:
                        month = obj['name']
                        month_int = int(datetime.strptime(month, "%B").month)
                        if not latest_date:
                            latest_date = current_sg_time()
                        if not month_int < latest_date.month:
                            months.append((month_int, year_int))
            else:
                continue

        return months

    def get_az_df(self, manager):
        az_df = manager.find_all_dates()
        mask = ((az_df["date"] >= self.latest_date) | (az_df.isna().any(axis=1)))
        self.logger.info("printing az dtypes")
        # self.logger.info(self.cur_az_df.dtypes)
        # self.logger.info(self.cur_az_df.info())
        # self.logger.info(self.cur_az_df)
        return az_df.loc[mask]

    def get_db_df(self, mm, yy):
        session = get_session()

        rows = session.query(
            LeaveRecord.id,
            LeaveRecord.date,
            User.name,
            User.dept,
            JobLeave.leave_type,
            LeaveRecord.leave_status,
            LeaveRecord.sync_status
        ).join(
            JobLeave, JobLeave.job_no == LeaveRecord.job_no
        ).join(
            User, JobLeave.user_id == User.id
        ).filter(
            LeaveRecord.leave_status != LeaveStatus.PENDING,
            extract('month', LeaveRecord.date) == mm,
            extract('year', LeaveRecord.date) == yy,
            LeaveRecord.date >= self.latest_date
        ).all()

        # self.logger.info("printing db dtypes")
        # self.logger.info(db_df.info())
        # self.logger.info(db_df.dtypes)
        df = pd.DataFrame(rows, columns=['record_id', 'date', 'name', 'dept', 'leave_type', 'leave_status', 'sync_status'])

        enum_cols = ['leave_type', 'sync_status', 'leave_status']
        for enum_col in enum_cols:
            df[enum_col] = df[enum_col].apply(lambda x: x.value if x else None)

        return df

    def get_all_mmyy_in_db(self):
        from models.jobs.leave.LeaveRecord import LeaveRecord

        session = get_session()

        stmt = (
            select(
                cast(func.extract('month', LeaveRecord.date), Integer).label('month'),
                cast(func.extract('year', LeaveRecord.date), Integer).label('year')
            ).filter(
                LeaveRecord.date >= self.latest_date
            )
            .distinct()
            .order_by('year', 'month')
        )

        results = session.execute(stmt).fetchall()

        return [(month, year) for month, year in results]
    
    def update_records(self, type, status, name, date):
        self.logger.info(f"type: {type}, status: {status}, name: {name}, date: {date}")
        if name not in self.records[type][status]:
            self.records[type][status][name] = []
        self.records[type][status][name].append(date)

    @classmethod
    def format_row(cls, row):
        cls.logger.info("printing row")
        cls.logger.info(row)
        cls.logger.info(list(type(obj) for obj in row))
        date_str = f"'{row['date'].strftime('%d/%m/%Y')}"
        return [row['record_id']] + [date_str] + [str(row[col]) for col in ['name', 'dept', 'leave_type']]
    
    def get_forward_metadata(self):
        session = get_session()

        cv_list = []
        users_list = []

        unique_names = {name for all_action_records in self.records.values() for records in all_action_records.values() for name in records.keys()}
        users = session.query(User).filter(User.name.in_(unique_names)).all()
        user_dict = {user.name: user for user in users}

        for action, all_action_records in self.records.items(): # add and del dicts
            for status, records in all_action_records.items():
                if len(records) == 0:
                    continue
                
                for name, dates in records.items():
                    user = user_dict.get(name)
                    if not user:
                        continue

                    cv = {
                        '1': "Addition" if action == Update.ADD else "Deletion",
                        '2': "successful" if status == Status.COMPLETED else "unsuccessful",
                        '3': print_all_dates(dates, date_obj=True),
                    }

                    cv_list.append(cv)
                    users_list.append(user)

        return MessageKnown.construct_forward_metadata(os.environ.get('SHAREPOINT_LEAVE_SYNC_NOTIFY_SID'), cv_list, users_list)

    






            
            

            

