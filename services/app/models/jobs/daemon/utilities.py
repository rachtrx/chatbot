import os
import time

from models.exceptions import AzureSyncError

from models.messages.MessageKnown import MessageKnown

from models.jobs.leave.constants import PM_HOUR

def generate_header(token=None):
    
    if not token:
        with open(os.getenv('TOKEN_PATH'), 'r') as file:
            token = file.read().strip()

    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }

    return headers

def delay_decorator(message, seconds = 1, retries = 5):
    def outer_wrapper(func):
        def inner_wrapper(*args, **kwargs):
            count = 0
            while (count < retries):
                response = func(*args, **kwargs)
                # logging.info(f"{response.status_code}, {response.text}")
                if 200 <= response.status_code < 300:
                    return response
                else:
                    time.sleep(seconds)
                count += 1
            raise AzureSyncError(f"{message}. {response.text}")
            
        return inner_wrapper
    return outer_wrapper

def inform_dept_admins_all_present(admin_list, job_no, date, err_msg=None, dept=None, is_evening=False, sid=os.getenv("SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID")):

    greeting = 'Evening' if is_evening else 'Morning'
    ext = 'will be' if is_evening else 'are'
    day = 'tomorrow' if is_evening else 'today'
    last_update = f'. As of {PM_HOUR}:00' if is_evening else ''

    MessageKnown.forward_template_msges(
        job_no=job_no,
        **MessageKnown.construct_forward_metadata(
            sid=sid, 
            cv_list=[{
                '1': f'{greeting} {admin.alias}{last_update}',
                '2': f'{dept or admin.dept} {ext}',
                '3': f'{day}, {date}',
                '4': f'Potential issue detected: {err_msg}' if err_msg else 'No other errors detected',
            } for admin in admin_list], 
            users_list=admin_list
        )
    )