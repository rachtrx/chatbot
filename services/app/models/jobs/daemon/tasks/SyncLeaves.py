import os
import json
import traceback
import requests
import pandas as pd

from datetime import datetime, timedelta
from sqlalchemy import select, func, extract, cast, Integer

from extensions import Session

from models.users import User

from models.exceptions import AzureSyncError

from models.jobs.base.utilities import current_sg_time, print_all_dates
from models.jobs.base.constants import Status

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.SpreadsheetManager import SpreadsheetManager
from models.jobs.daemon.utilities import generate_header
from models.jobs.daemon.constants import Update, Link, DaemonMessage, DaemonTaskType

from models.jobs.leave.constants import LeaveStatus, LeaveType
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.Job import JobLeave

from models.messages.MessageKnown import MessageKnown

class SyncLeaves(TaskDaemon):

    name = "Leave Records Sync"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SYNC_LEAVES
    }

    def get_err_body(self) -> str:
        return DaemonMessage.SYNC_FAILED + self.unmatched_records_body if self.unmatched_records_body else ""

    def execute(self):
        self.unmatched_records_body = None

        self.start_time = current_sg_time()
        self.latest_date = self.start_time.date() - timedelta(days=1)

        self.records = {
            Update.ADD: {Status.FAILED: {}, Status.COMPLETED: {}},
            Update.DEL: {Status.FAILED: {}, Status.COMPLETED: {}}
        }

        session = Session()

        az_mmyy_arr = self.loop_leave_files()
        db_mmyy_arr = self.get_all_mmyy_in_db()

        combined_mmyy_set = set(az_mmyy_arr) | set(db_mmyy_arr)

        # self.logger.info(f"Combined list: {combined_mmyy_list}")

        missing_job_user_ids = {}

        error = False

        for mm, yy in combined_mmyy_set: # contains the mm, yy that are >= ysterday

            # self.logger.info(f"month: {mm}, year: {yy}")

            cur_manager = SpreadsheetManager(mmyy=[mm, yy])

            # get azure df
            cur_az_df = self.get_az_df(cur_manager)

            self.logger.info("current AZ dataframe: ")
            self.logger.info(cur_az_df)

            # get db df, including cancelled records
            cur_db_df = self.get_db_df(mm, yy)

            # dates_to_del: in az, not in db. dates_to_update: in db, not in az
            combined_df = pd.merge(cur_az_df, cur_db_df, how="outer", indicator=True)
            combined_df['_merge'] = combined_df['_merge'].replace({'left_only': 'az_only', 'right_only': 'db_only'})

            self.logger.info(f"Combined DF: {combined_df}")
            self.logger.info(combined_df.info())

            if combined_df.empty:
                self.logger.info("Combined DF is empty")
                continue
            
            # FIND ANY UNUPDATED RECORDS
            completed_ids = combined_df.loc[((combined_df._merge == "both") & (combined_df.leave_status == LeaveStatus.APPROVED)) & (~(combined_df.sync_status == Status.COMPLETED)), "record_id"]            
            if not completed_ids.empty:
                session.bulk_update_mappings(LeaveRecord, [
                    {'id': completed_id, 'sync_status': Status.COMPLETED }
                    for completed_id in completed_ids
                ])

            # both but cancelled or az only (no record ever made in local db) means have to del from Sharepoint
            combined_df.loc[((combined_df._merge == "both") & (~(combined_df.leave_status == LeaveStatus.APPROVED)) | (combined_df._merge == "az_only")), "action"] = Update.DEL
            # PASS: both and not cancelled means updated on both sides
            # db only and not cancelled means need to add to Sharepoint
            combined_df.loc[((combined_df._merge == "db_only") & (combined_df.leave_status == LeaveStatus.APPROVED)), "action"] = Update.ADD
            # PASS: right only and cancelled means updated on both sides

            dates_to_del = combined_df.loc[combined_df.action == Update.DEL].copy()
            dates_to_update = combined_df.loc[combined_df.action == Update.ADD].copy()

            # self.logger.info("Printing dates to del and add")
            self.logger.info(f"To del: {dates_to_del}")
            self.logger.info(f"To Add: {dates_to_update}")
            self.logger.info(f"length of data to del: {dates_to_del.shape}")
            self.logger.info(f"length of data to add: {dates_to_update.shape}")

            if dates_to_del.empty and dates_to_update.empty:
                self.logger.info(f"dates_to_del is empty: {dates_to_del.empty}, dates_to_update is empty: {dates_to_update.empty}")
                continue
            
            del_status = add_status = Status.COMPLETED

            if not dates_to_del.empty:
                # delete from excel
                indexes_to_rm = dates_to_del["az_index"].dropna().astype(int).tolist()
                self.logger.info(f"indexes to remove: {indexes_to_rm}")

                # cancel MCs
                try:
                    cur_manager.delete_from_excel(indexes_to_rm)
                except AzureSyncError as e:
                    del_status = Status.FAILED
                    error = True
                    self.logger.error(e)
                
                del_grouped = dates_to_del.groupby(['_merge', 'user_id'], observed=True)
                for (_merge, user_id), group in del_grouped:
                    del_dates = [date for date in group['date'] if not pd.isna(date)]
                    if _merge == "az_only": # blank row / no match with db. if no match and name: send a spearate message
                        if user_id and not pd.isna(user_id) and len(del_dates) > 0:
                            self.logger.info(f"User ID added: {user_id}")
                            if user_id not in missing_job_user_ids:
                                missing_job_user_ids[user_id] = []
                            missing_job_user_ids[user_id].extend(del_dates)
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
                        self.update_records(Update.DEL, del_status, user_id, record.date)
            
            if not dates_to_update.empty:
                data_to_add = list(dates_to_update.apply(self.format_row, axis=1))
                try:
                    cur_manager.upload_data(data_to_add)
                except AzureSyncError as e:
                    add_status = Status.FAILED
                    error = True
                    self.logger.error(e)

                add_grouped = dates_to_update.groupby(['_merge', 'user_id'], observed=True)
                for (_merge, user_id), group in add_grouped:

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
                        self.update_records(Update.ADD, add_status, user_id, record.date)

        if any(len(users_dict) > 0 for statuses in self.records.values() for users_dict in statuses.values()):
            self.logger.info("sending messages")
            self.logger.info(f"records of new leaves: {self.records}")
        
            MessageKnown.forward_template_msges(
                self.job.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user.id,
                message_context='their updating of leaves',
                **self.get_forward_metadata()
            )

            if error:
                self.body = DaemonMessage.AZURE_CONN_FAILED
            else:
                self.body = DaemonMessage.SYNC_COMPLETED

        else:
            self.body = DaemonMessage.NOTHING_TO_SYNC

        self.logger.info(f"Missing Job User IDs dict: {missing_job_user_ids}")

        if len(missing_job_user_ids) > 0:
            unmatched_records = '; '.join(f"{name}: {print_all_dates(date_list)}" for name, date_list in missing_job_user_ids.items())
            self.unmatched_records_body = f" Unmatched records were found in Azure: {unmatched_records}"
            self.body += self.unmatched_records_body

        if error:
            raise Exception

    def get_az_df(self, manager):
        data = manager.find_all_dates()

        df = pd.DataFrame(
            data = data, 
            columns = ["date", "name", "dept", "leave_type", "user_id", "record_id"], 
            dtype='string'
        )

        # Get original Azure Index
        df.replace('', pd.NA, inplace=True)
        df['date'] = df['date'].str.strip()

        df = df.reset_index(drop=False).rename(columns={'index': 'az_index'})

        df = df.astype({
            "date": 'object',
            "name": str, 
            "dept": str, 
            "leave_type": str,
            "user_id": str, 
            "record_id": str, 
            "az_index": int, 
        })
        
        df['leave_type'] = df['leave_type'].apply(lambda x: x.upper())

        empty_date_mask = df['date'].isna()
        df.loc[~empty_date_mask, 'date'] = pd.to_datetime(df.loc[~empty_date_mask, 'date'], format='%d/%m/%Y').dt.date
        
        mask = ((df["date"] >= self.latest_date) | (df.isna().any(axis=1))) # also select any rows with missing data
        self.logger.info(f"AZ Metadata: {df.info()}")
        self.logger.info(f"AZ Dataframe: {df}")

        return df.loc[mask]

    def get_db_df(self, mm, yy):
        session = Session()

        rows = session.query(
            LeaveRecord.date,
            User.name,
            User.dept,
            JobLeave.leave_type,
            User.id,
            LeaveRecord.id,
            LeaveRecord.leave_status,
            LeaveRecord.sync_status,
        ).join(
            JobLeave, JobLeave.job_no == LeaveRecord.job_no
        ).join(
            User, JobLeave.primary_user_id == User.id
        ).filter(
            LeaveRecord.leave_status != LeaveStatus.PENDING,
            extract('month', LeaveRecord.date) == mm,
            extract('year', LeaveRecord.date) == yy,
            LeaveRecord.date >= self.latest_date
        ).all()

        df = pd.DataFrame(
            rows, 
            columns=['date', 'name', 'dept', 'leave_type', 'user_id', 'record_id', 'leave_status', 'sync_status'],
            dtype='object'
        )

        # df['leave_type'] = df['leave_type'].apply(lambda x: x.value)

        df = df.astype({
            "date": 'object',
            "name": str, 
            "dept": str,
            "leave_type": str,
            "user_id": str, 
            "record_id": str, 
            "leave_status": 'object', 
            "sync_status": 'object',
        })

        self.logger.info(f"DB Metadata: {df.info()}")
        self.logger.info(f"DB Dataframe: {df}")
        return df
    
    def update_records(self, type, status, user_id, date):
        self.logger.info(f"type: {type}, status: {status}, user_id: {user_id}, date: {date}")
        if user_id not in self.records[type][status]:
            self.records[type][status][user_id] = []
        self.records[type][status][user_id].append(date)

    @classmethod
    def format_row(cls, row):
        cls.logger.info("printing row")
        cls.logger.info(row)
        cls.logger.info(list(type(obj) for obj in row))
        date_str = f"'{row['date'].strftime('%d/%m/%Y')}"
        return [date_str] + [str(row[col]) for col in ['name', 'dept', 'leave_type', 'user_id', 'record_id']]
    
    def get_forward_metadata(self):
        session = Session()

        cv_list = []
        users_list = []

        for action, all_action_records in self.records.items(): # add and del dicts
            for status, records in all_action_records.items():
                if len(records) == 0:
                    continue
                
                for user_id, dates in records.items():
                    user = session.query(User).get(user_id)
                    if not user:
                        continue

                    cv = {
                        '1': "Addition" if action == Update.ADD else "Deletion",
                        '2': "successful" if status == Status.COMPLETED else "unsuccessful",
                        '3': print_all_dates(dates),
                    }

                    cv_list.append(cv)
                    users_list.append(user)

        return MessageKnown.construct_forward_metadata(os.getenv('SHAREPOINT_LEAVE_SYNC_NOTIFY_SID'), cv_list, users_list)

    def get_all_mmyy_in_db(self):
        from models.jobs.leave.LeaveRecord import LeaveRecord

        session = Session()

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

    def loop_leave_files(self, leave_files_url = Link.LEAVE_FILES_URL):

        self.logger.info(f"Leave Files URL: {leave_files_url}")

        header = generate_header()

        # self.logger.info(leave_files_url)
        response = requests.get(url=leave_files_url, headers=header)

        # self.logger.info(header)

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
                        if not month_int < self.latest_date.month:
                            months.append((month_int, year_int))
            else:
                continue

        return months





            
            

            

