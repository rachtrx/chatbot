from sqlalchemy import select, func, extract, cast, Integer
from azure.sheet_manager import SpreadsheetManager
import requests
from utilities import current_sg_time
from datetime import datetime, timedelta
from azure.utils import loop_leave_files, generate_header
from models.jobs.system.abstract import JobSystem
from MessageLoggersetup_logger
from extensions import db, get_session
import pandas as pd
from models.exceptions import AzureSyncError, ReplyError
from constants import Intent, JobStatus, LeaveStatus
import os
import traceback
from utilities import print_all_dates
from models.users import User
import json

class JobSyncRecords(JobSystem):

    logger = setup_logger('models.job_sync_records')

    __tablename__ = 'job_sync_records'

    job_no = db.Column(db.ForeignKey("job_system.job_no", ondelete='CASCADE'), primary_key=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_sync_records",
    }

    def __init__(self):
        super().__init__() # admin name is default
        self.header = generate_header()
        self.cur_az_df = None
        self.cur_db_df = None
        self.start_time = current_sg_time()
        self.latest_date = self.start_time.date() - timedelta(days=1)
        self.cur_manager = None
        self.content_sid = os.environ.get('SHAREPOINT_LEAVE_SYNC_NOTIFY_SID')
        self.records = {
            Intent.SHAREPOINT_ADD_RECORD: {JobStatus.SERVER_ERROR: {}, JobStatus.OK: {}},
            Intent.SHAREPOINT_DEL_RECORD: {JobStatus.SERVER_ERROR: {}, JobStatus.OK: {}}
        }
        self.cv_and_users_list = []
        self.content_sid = os.environ.get('SHAREPOINT_LEAVE_SYNC_NOTIFY_SID')

    def get_az_df(self):
        az_df = self.cur_manager.find_all_dates()
        mask = ((az_df["date"] >= self.latest_date) | (az_df.isna().any(axis=1)))
        self.cur_az_df = az_df.loc[mask]
        self.logger.info("printing az dtypes")
        # self.logger.info(self.cur_az_df.dtypes)
        # self.logger.info(self.cur_az_df.info())
        # self.logger.info(self.cur_az_df)

    def get_db_df(self, mm, yy):
        from models.jobs.user.leave import JobLeave
        from models.leave_records import LeaveRecord
        from models.users import User

        session = get_session()

        rows = session.query(
            LeaveRecord.id,
            LeaveRecord.date,
            User.name,
            User.dept,
            JobLeave.leave_type,
            JobLeave.leave_status,
            LeaveRecord.sync_status
        ).join(
            LeaveRecord, JobLeave.job_no == LeaveRecord.job_no
        ).join(
            User, JobLeave.name == User.name
        ).filter(
            JobLeave.leave_status != LeaveStatus.PENDING,
            extract('month', LeaveRecord.date) == mm,
            extract('year', LeaveRecord.date) == yy,
            LeaveRecord.date >= self.latest_date
        ).all()

        db_df = pd.DataFrame(rows, columns=['record_id', 'date', 'name', 'dept', 'leave_type', 'leave_status', 'sync_status'])
        # self.logger.info("printing db dtypes")
        # self.logger.info(db_df.info())
        # self.logger.info(db_df.dtypes)
        self.cur_db_df = db_df

    def get_all_mmyy_in_db(self):
        from models.leave_records import LeaveRecord

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

        return [[month, year] for month, year in results]
    
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
    
    def get_sharepoint_leave_sync_notify_cv(self):
        session = get_session()

        for action, all_action_records in self.records.items(): # add and del dicts
            for status, records in all_action_records.items():
                if len(records) == 0:
                    continue
                else:
                    for name, dates in records.items():
                        user = session.query(User).filter_by(name=name).first()
                        if not user:
                            continue

                        cv = {
                            '1': "Addition" if action == Intent.SHAREPOINT_ADD_RECORD else "Deletion",
                            '2': "successful" if status == JobStatus.OK else "unsuccessful",
                            '3': print_all_dates(dates, date_obj=True),
                        }

                        self.cv_and_users_list.append((json.dumps(cv), user))
    

    def main(self):
        from models.leave_records import LeaveRecord
        from models.messages.sent import MessageForward

        session = get_session()

        self.az_mmyy_arr = loop_leave_files(latest_date=self.latest_date)
        # self.logger.info(self.az_mmyy_arr)
        self.db_mmyy_arr = self.get_all_mmyy_in_db()
        # self.logger.info(self.db_mmyy_arr)

        db_mmyy_set = set(tuple(mmyy) for mmyy in self.db_mmyy_arr)
        az_mmyy_set = set(tuple(mmyy) for mmyy in self.az_mmyy_arr)
        combined_mmyy_set = db_mmyy_set | az_mmyy_set
        combined_mmyy_list = [list(mmyy) for mmyy in combined_mmyy_set]

        # self.logger.info(f"Combined list: {combined_mmyy_list}")

        all_missing_job_names = {}

        for mm, yy in combined_mmyy_list: # contains the mm, yy that are >= ysterday

            # self.logger.info(f"month: {mm}, year: {yy}")

            self.cur_manager = SpreadsheetManager(mmyy=[mm, yy])

            # get azure df
            self.get_az_df()

            # get db df, including cancelled records
            self.get_db_df(mm, yy)

            # dates_to_del: in az, not in db. dates_to_update: in db, not in az
            combined_df = pd.merge(self.cur_az_df, self.cur_db_df, how="outer", indicator=True)
            combined_df['_merge'] = combined_df['_merge'].replace({'left_only': 'az_only', 'right_only': 'db_only'})

            self.logger.info("Printing combined df")
            self.logger.info(combined_df)
            self.logger.info(combined_df.dtypes)

            if combined_df.empty:
                self.commit_status(JobStatus.OK, _forwards=True)
                self.reply = "Nothing to sync"
                return

            # both but cancelled or az only (no record ever made in local db) means have to del from Sharepoint
            combined_df.loc[(((combined_df._merge == "both") & (combined_df.leave_status == LeaveStatus.CANCELLED)) | (combined_df._merge == "az_only")), "action"] = Intent.SHAREPOINT_DEL_RECORD
            # PASS: both and not cancelled means updated on both sides
            # db only and not cancelled means need to add to Sharepoint
            combined_df.loc[((combined_df._merge == "db_only") & (combined_df.leave_status == LeaveStatus.APPROVED)), "action"] = Intent.SHAREPOINT_ADD_RECORD
            # PASS: right only and cancelled means updated on both sides

            dates_to_del = combined_df.loc[combined_df.action == Intent.SHAREPOINT_DEL_RECORD].copy()
            dates_to_update = combined_df.loc[combined_df.action == Intent.SHAREPOINT_ADD_RECORD].copy()

            # self.logger.info("Printing dates to del and add")
            # self.logger.info(dates_to_del)
            # self.logger.info(dates_to_update)
            self.logger.info(f"length of data to del: {dates_to_del.shape}")
            self.logger.info(f"length of data to add: {dates_to_update.shape}")

            if dates_to_del.empty and dates_to_update.empty:
                self.commit_status(JobStatus.OK, _forwards=True)
                self.reply = "Nothing to sync"
                return
            
            if not dates_to_del.empty:
                # delete from excel
                indexes_to_rm = dates_to_del["az_index"].dropna().astype(int).tolist()
                self.logger.info(f"indexes to remove: {indexes_to_rm}")

                # cancel MCs
                try:
                    self.cur_manager.delete_from_excel(indexes_to_rm)
                    del_status = JobStatus.OK
                except AzureSyncError as e:
                    self.error = True
                    del_status = JobStatus.SERVER_ERROR
                    self.logger.error(e.message)
                
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
                    
                    for id in group['record_id'].tolist():
                        record = session.query(LeaveRecord).filter_by(id=id).first()
                        if record and record.sync_status != del_status: 
                            record.sync_status = del_status
                            self.update_records(Intent.SHAREPOINT_DEL_RECORD, del_status, name, record.date)

            # Add MCs
            # add to excel
            
            if not dates_to_update.empty:
                data_to_add = list(dates_to_update.apply(self.format_row, axis=1))
                try:
                    self.cur_manager.upload_data(data_to_add)
                    add_status = JobStatus.OK
                except AzureSyncError as e:
                    self.error = True
                    add_status = JobStatus.SERVER_ERROR
                    self.logger.error(e.message)

                add_grouped = dates_to_update.groupby(['_merge', 'name'], observed=True)
                for (_merge, name), group in add_grouped:
                    for id in group['record_id'].tolist():
                        record = session.query(LeaveRecord).filter_by(id=id).first()
                        if record and record.sync_status != add_status: 
                            record.sync_status = add_status
                            self.logger.info(f"add record number: {Intent.SHAREPOINT_ADD_RECORD}")
                            self.update_records(Intent.SHAREPOINT_ADD_RECORD, add_status, name, record.date)
            session.commit()

        if len(self.records) > 0:
            self.logger.info("sending messages")
            self.logger.info(f"records of new leaves: {self.records}")
            self.get_sharepoint_leave_sync_notify_cv()
            self.logger.info(f"content variables: {self.cv_and_users_list}")
            MessageForward.forward_template_msges(self)

        if self.error == True:
            self.reply = "Error connecting to Azure"
        else:
            self.reply = "Sync was successful"

            if len(all_missing_job_names) > 0:
                names_dates_str = '; '.join(f"{name}: {print_all_dates(date_list, date_obj=True)}" for name, date_list in all_missing_job_names.items())
                self.reply += f". Also, unmatched records were found in Azure: {names_dates_str}"

    






            
            

            

