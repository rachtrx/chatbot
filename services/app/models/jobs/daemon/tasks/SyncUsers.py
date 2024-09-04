import requests
import pandas as pd
import numpy as np
import shortuuid

from extensions import Session

from models.users import User
from models.lookups import Lookup
from models.exceptions import AzureSyncError, DaemonTaskError

from models.jobs.base.utilities import join_with_commas_and

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import Link, DaemonTaskType, DaemonMessage
from models.jobs.daemon.utilities import generate_header

USER_COLS = ['name', 'alias', 'number', 'dept', 'is_global_admin', 'is_dept_admin', 'is_active']

class SyncUsers(TaskDaemon):

    name = "Users Sync"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SYNC_USERS
    }

    def execute(self):
        self.failed_users = []
        self.affected_users = []
        try:
            self.header = generate_header()
            self.update_user_database()
        except AzureSyncError as e:
            self.logger.error(e)
            raise DaemonTaskError(DaemonMessage.AZURE_CONN_FAILED)
        except Exception:
            err_body = DaemonMessage.UNKNOWN_ERROR
            if len(self.failed_users) > 0:
                err_body += ". Failed: " + [join_with_commas_and(self.failed_users)]
            if len(self.affected_users) > 0:
                err_body += ". Affected: " + [join_with_commas_and(self.affected_users)]
            raise DaemonTaskError(err_body)
        
    def get_az_table_data(self, url):

        '''Returns a 2D list containing the user details within the inner array'''

        response = requests.get(url=url, headers=self.header)

        try:
            data = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
        except KeyError:
            raise AzureSyncError(DaemonMessage.AZURE_CONN_FAILED)

        self.logger.info(f"AZ Data: {data}")
        return data # info is already a list so user_info is a 2D list

    @staticmethod
    def clean_df(df):
        '''Replaces empty strings with NaN, removes entirely blank rows, and sets empty aliases to names.'''
        df = df.replace({np.nan: None, '': None })
        df = df.dropna(how="all")
        df.loc[df['alias'].isnull(), 'alias'] = df['name']
        df['number'] = df['number'].str.replace(' ', '', regex=True)
        return df

    def update_user_database(self):

        session = Session()

        # SECTION AZURE SIDE
        az_users_table_data = self.get_az_table_data(Link.USERS_TABLE_URL)

        az_users_df = pd.DataFrame(
            data=az_users_table_data, 
            columns=["name", "alias", "number", "dept", "reporting_officer", "appointment", "access"],
            dtype='string'
        )

        az_users_df = self.clean_df(az_users_df)
        az_users_df = az_users_df.drop(columns=['appointment'])

        # Set data types
        data_types = {
            'name': 'str',
            'alias': 'str',
            'number': 'int',
            'dept': 'str',
            'reporting_officer': 'str',
            'lookup': 'str',
            'access': 'str',
        }

        for column in az_users_df.columns:
            dtype = data_types.get(column)
            if not dtype:
                raise DaemonTaskError(f'{column} data type not found')
            az_users_df[column] = az_users_df[column].astype(dtype)

        try:
            az_users_df['number'] = az_users_df["number"].astype(int)
        except:
            az_users_df['temp_number'] = pd.to_numeric(az_users_df['number'], errors='coerce')
            problematic_rows = az_users_df[az_users_df['temp_number'].isna()]
            self.failed_users.extend(join_with_commas_and(problematic_rows['name'].tolist()))
            raise Exception

        az_users_df['is_global_admin'] = (az_users_df['access'] == 'GLOBAL')
        az_users_df['is_dept_admin'] = (az_users_df['access'] == 'DEPT')
        # az_users_df['is_global_admin'] = az_users_df['is_global_admin'].astype('bool')
        # az_users_df['is_dept_admin'] = az_users_df['is_dept_admin'].astype('bool')
        az_users_df['is_active'] = True

        az_users = az_users_df[USER_COLS].copy() # need az_df for reporting officer later
        

        db_df = pd.read_sql(session.query(User).statement, session.bind)
        db_users = db_df[[*USER_COLS, 'id']].copy()

        self.logger.info(f"azure users: {az_users}")
        self.logger.info(f"db_users users: {db_users}")
        self.logger.info(f"az_users columns: {az_users.columns}")
        self.logger.info(f"db_users columns: {db_users.columns}")

        self.logger.info("checking for exact match")

        if not self.check_for_exact_match(az_users[USER_COLS], db_users.loc[db_users['is_active'] == True, USER_COLS]):

            self.logger.info("not exact match")

            MATCH_ON_COLS = ['name', 'number']

            # Perform the merge operation with indicators
            merged_users = pd.merge(
                az_users, 
                db_users,
                on=MATCH_ON_COLS,
                how="outer", 
                indicator=True,
                suffixes=('', '_old')
            )

            merged_users.replace({pd.NA: None, pd.NaT: None, "": None}, inplace=True)

            old_user_ids = merged_users.loc[(merged_users['_merge'] == 'right_only') & (merged_users['is_active_old'] == True), 'id']

            COLS_TO_COMPARE = [col for col in USER_COLS if col not in MATCH_ON_COLS] # 5 cols

            updated_users = merged_users.loc[(merged_users['_merge'] == 'both')]
            differences = pd.DataFrame({col: updated_users[f"{col}_old"] != updated_users[col] for col in COLS_TO_COMPARE}).any(axis=1)

            COLS_TO_UPDATE = ['id'] + [col for col in COLS_TO_COMPARE if col != 'is_active'] # 5 cols
            updated_users = updated_users.loc[differences, COLS_TO_UPDATE]
            updated_users_tuples = [tuple(updated_user) for updated_user in updated_users.values]

            COLS_TO_ADD = ['id'] + [col for col in USER_COLS if col != 'is_active'] # 7 cols
            new_users = merged_users.loc[merged_users['_merge'] == 'left_only', COLS_TO_ADD]
            new_users['id'] = [shortuuid.ShortUUID().random(length=8).upper() for _ in range(len(new_users))]
            new_users_tuples = [tuple(new_user) for new_user in new_users.values]
            
            self.logger.info(f"Updating users.")
            self.logger.info(f"New users: {new_users_tuples}")
            self.logger.info(f"Updated users: {updated_users_tuples}")
            self.logger.info(f"Old user IDs: {old_user_ids}")

            session.bulk_update_mappings(User, [
                {'id': user_id, 'is_active': False }
                for user_id in old_user_ids.values
            ])

            session.query(Lookup).filter(Lookup.user_id.in_(old_user_ids.values)).delete(synchronize_session=False)

            session.bulk_update_mappings(User, [
                {'id': user_id, 'alias': alias, 'dept': dept, 'is_global_admin': is_global_admin, 'is_dept_admin': is_dept_admin, 'is_active': True }
                for user_id, alias, dept, is_global_admin, is_dept_admin in updated_users_tuples
            ])

            session.bulk_insert_mappings(User, [
                {'id': user_id, 'name': name, 'alias': alias, 'number': number, 'dept': dept, 'is_global_admin': is_global_admin, 'is_dept_admin': is_dept_admin, 'is_active': True }
                for user_id, name, alias, number, dept, is_global_admin, is_dept_admin in new_users_tuples
            ])

            session.commit()

        # map the Reporting Officers
        az_lookup_table_data = self.get_az_table_data(Link.LOOKUP_TABLE_URL)

        az_ro_df = az_users_df.loc[
            (~az_users_df['reporting_officer'].isnull()) & (az_users_df['reporting_officer'] != ''),
            ['name', 'reporting_officer']
        ].rename(columns={'reporting_officer': 'lookup'})

        self.logger.info(f"ro lookups: {az_ro_df}")

        az_non_ro_lookup_df = pd.DataFrame(
            data=az_lookup_table_data, 
            columns=["name", "lookup"],
            dtype='string'
        )

        self.logger.info(f"non ro lookups: {az_non_ro_lookup_df}")

        az_lookup_df = pd.merge(
            az_ro_df,
            az_non_ro_lookup_df,
            how='outer',
            indicator=True
        )

        self.logger.info(f"merged lookups: {az_lookup_df}")

        az_lookup_df['is_reporting_officer'] = az_lookup_df['_merge'].map({
            'both': True,
            'left_only': True,
            'right_only': False
        })
        az_lookup_df.drop(columns=['_merge'], inplace=True)

        db_mapping_df = pd.read_sql(session.query(User.name, User.id).filter(User.is_active == True).statement, session.bind)
        name_to_id_map = dict(zip(db_mapping_df['name'], db_mapping_df['id']))
        az_lookup_df['lookup_id'] = az_lookup_df['lookup'].map(name_to_id_map)
        az_lookup_df['user_id'] = az_lookup_df['name'].map(name_to_id_map)
        
        db_lookup_df = pd.read_sql(session.query(Lookup.id, Lookup.user_id, Lookup.lookup_id, Lookup.is_reporting_officer).statement, session.bind)

        az_lookup_df = az_lookup_df[['user_id', 'lookup_id', 'is_reporting_officer']]
        db_lookup_df = db_lookup_df[['id', 'user_id', 'lookup_id', 'is_reporting_officer']]

        az_lookup_df = az_lookup_df.dropna(subset=['user_id', 'lookup_id'])
        az_lookup_df = az_lookup_df.where(pd.notna(az_lookup_df), None) # Replace NaN values with None
        db_lookup_df = db_lookup_df.where(pd.notna(db_lookup_df), None)

        self.logger.info(f"az_lookup_df: {az_lookup_df}")
        self.logger.info(f"db_lookup_df: {db_lookup_df}")
        self.logger.info("Checking exact match for RO")

        # SECTION check for exact match
        if not self.check_for_exact_match(az_lookup_df, db_lookup_df.drop(columns=['id'])):

            self.logger.info("No exact match for RO")

            merged_lookups = pd.merge(
                az_lookup_df, 
                db_lookup_df,
                on=['user_id', 'lookup_id', 'is_reporting_officer'],
                how="outer",
                indicator=True,
            )

            self.logger.info(f"Lookups: {merged_lookups}")

            old_lookup_records = merged_lookups.loc[merged_lookups['_merge'] == 'right_only', 'id']
            new_lookups = merged_lookups.loc[merged_lookups['_merge'] == 'left_only'].drop(columns=['id', '_merge'])

            new_lookup_tuples = [tuple(new_lookup) for new_lookup in new_lookups.values]

            self.logger.info(f"New lookups: {new_lookup_tuples}")
            self.logger.info(f"Old lookups: {old_lookup_records}")

            session.query(Lookup).filter(Lookup.id.in_(old_lookup_records.values)).delete(synchronize_session=False)

            session.bulk_insert_mappings(Lookup, [
                {'id': shortuuid.ShortUUID().random(length=8).upper(), 'user_id': user_id, 'lookup_id': lookup_id, 'is_reporting_officer': is_reporting_officer }
                for user_id, lookup_id, is_reporting_officer in new_lookup_tuples
            ])

            session.commit()

            self.logger.info("Updated RO")
        
    def check_for_exact_match(self, df1, df2):

        if set(df1.columns) != set(df2.columns):
            self.logger.info("Columns are different")
            return False  # Return False if they do not have the same columns

        common_columns = list(df1.columns)
        df1 = df1[common_columns].sort_index(axis=1)
        df2 = df2[common_columns].sort_index(axis=1)

        df1_sorted = df1.sort_values(by=common_columns).reset_index(drop=True)
        df2_sorted = df2.sort_values(by=common_columns).reset_index(drop=True)

        # pd.set_option('display.max_columns', None)

        return df1_sorted.equals(df2_sorted)

    
