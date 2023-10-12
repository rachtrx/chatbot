import msal
import os
import requests
from dotenv import load_dotenv

NUMBER_INDEX = 1

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

USERS_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/{os.environ.get('USERS_SHEET_ID')}/tables('MainTable')/rows"
# LOOKUP_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/{os.environ.get('USERS_SHEET_ID')}/tables('Tables')/rows"

# Enter details of AAD app registration

config = {
    'client_id': os.environ.get('CLIENT_ID'),
    'client_secret': os.environ.get('CLIENT_SECRET'),
    'authority': os.environ.get('AUTHORITY'),
    'scope': [os.environ.get('SCOPE')],
    'site_id': os.environ.get('SITE_ID'),
}


def get_user_info(from_number, msal_instance, scope):
    '''Returns a 2D list containing the user details within the inner array'''

    # First, try to lookup an access token in cache
    token_result = msal_instance.acquire_token_silent(scope, account=None)

    # If the token is available in cache, save it to a variable
    if token_result:
        print('Access token was loaded from cache')

    # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
    if not token_result:
        token_result = msal_instance.acquire_token_for_client(scopes=scope)
        print(token_result)
        access_token = 'Bearer ' + token_result['access_token']
        print(f'New access token {access_token} was acquired from Azure AD')


    # Copy access_toek and specify the MS Graph API endpoint you want to call, e.g. '
    headers = {
        'Authorization': access_token
    }

    # Make a GET request to the provided url, passing the access token in a header
    graph_result = requests.get(url=USERS_TABLE_URL, headers=headers)

    print([info[1] for object_info in graph_result.json()['value'] for info in object_info['values']])

    user_info = [info for object_info in graph_result.json()['value'] for info in object_info['values'] if int(info[NUMBER_INDEX]) == from_number]

    print(f"user info: {user_info}")

    return user_info # info is already a list so user_info is a 2D list

# create an MSAL instance providing the client_id, authority and client_credential params
def get_msal_instance():
    return msal.ConfidentialClientApplication(config['client_id'], authority=config['authority'], client_credential=config['client_secret'])