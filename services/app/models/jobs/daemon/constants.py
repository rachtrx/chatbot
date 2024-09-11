import os
from enum import Enum
import logging

logging.info(f"LIVE IN CONSTANTS: {int(os.getenv('LIVE'))}")

class Link:
    DRIVE_ID = os.getenv('DRIVE_ID')
    USERS_FILE_ID = os.getenv('USERS_FILE_ID') if int(os.getenv('LIVE')) else os.getenv('USERS_FILE_ID_DEV')
    LEAVE_FOLDER_ID = os.getenv('LEAVE_FOLDER_ID') if int(os.getenv('LIVE')) else os.getenv('LEAVE_FOLDER_ID_DEV')

    DRIVE_URL = f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}/items/"

    USERS_TABLE_URL = f"{DRIVE_URL}{USERS_FILE_ID}/workbook/worksheets/users/tables/UsersTable/rows"
    LOOKUP_TABLE_URL = f"{DRIVE_URL}{USERS_FILE_ID}/workbook/worksheets/lookups/tables/LookupsTable/rows"
    LEAVE_FILES_URL = f'{DRIVE_URL}{LEAVE_FOLDER_ID}/children'

class AccessLevel(Enum):
    GLOBAL = 'GLOBAL'
    DEPT = 'DEPT'
    STAFF = 'STAFF'

class Update(Enum):
    DEL = 'DEL'
    ADD = 'ADD'

class DaemonTaskType:
    NONE = 'NONE'
    ACQUIRE_TOKEN = 'ACQUIRE_TOKEN'
    SEND_AM_REPORT = 'SEND_AM_REPORT'
    SEND_PM_REPORT = 'SEND_PM_REPORT'
    SYNC_LEAVES = 'SYNC_LEAVES'
    SYNC_USERS = 'SYNC_USERS'
    CLEAN_TASKS = 'CLEAN_TASKS'

class DaemonMessage:
    TOKEN_ACQUIRED = "Access token retrieved."
    TOKEN_NOT_ACQUIRED = "Access token was *NOT* retrieved."
    SYNC_COMPLETED = "Sync was successful."
    REPORT_SENT = "Successfully sent, pending forward statuses."
    SECRET_EXPIRED = "Failed to retrieve token. Likely due to Client Secret Expiration. To create a new Client Secret, go to Microsoft Entra ID → Applications → App Registrations → Chatbot → Certificates & Secrets → New client secret. Then update the .env file and restart Docker."
    TABLE_URL_CHANGED = "Retrieved Token. Minor Issue with table URLs."
    AZURE_CONN_FAILED = "Error connecting to Azure."
    NOTHING_TO_SYNC = "Nothing to sync."
    SYNC_FAILED = "Sync failed."
    REPORT_FAILED = "Report failed to send."
    UNKNOWN_ERROR = "Unknown Error"
    
