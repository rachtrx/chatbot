from datetime import datetime, timedelta
import os
import requests
from dotenv import load_dotenv
from models import AzureSyncError, ReplyError, User
from utilities import delay_decorator
import pandas as pd
import json

def cur_datetime(dt_type):
    return datetime.now().strftime(dt_type)

def get_year():
    cur_date = datetime.now()
    format_date = cur_date.strftime("%Y")

    return format_date

class AzureSyncError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class SpreadsheetManager:
    def __init__(self):
        self.template_path = os.path.join(os.path.dirname(__file__), 'excel_files', 'mc_template.xlsx')
        self.drive_url = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}"
        self.folder_url = self.drive_url + f"/items/{os.environ.get('FOLDER_ID')}"
        print(f"drive_url: {self.drive_url}, folder_url = {self.folder_url}")

    @property
    def query_book_url(self):
        return self.folder_url + f"/children?$filter=name eq '{get_year()}.xlsx'"
    
    @property
    def create_book_url(self):
        return self.folder_url + f":/{get_year()}.xlsx:/content"

    @property
    def headers(self):
        # read the token from the file
        if os.environ.get('LIVE') == "1":
            # print("getting headers in azure upload")
            with open(os.environ.get('TOKEN_PATH'), 'r') as file:
                token = file.read().strip()

            headers = {
                'Authorization': token,
                'Content-Type': 'application/json'
            }
            
        else:
            token = os.environ.get('ACCESS_TOKEN')
            headers = {
                'Authorization': token,
                'Content-Type': 'application/json'
            }

        return headers
    
    @property
    def table_url(self):
        # get the workbook for this year
        # print(self.query_book_url)
        # print(self.headers)

        worksheets_url, new_book = self.get_sheets_url()

        # checks if sheet for this month exists, otherwise create it
        worksheet_url = self.get_sheet_url(worksheets_url)
        print(f"Worksheet URL FINAL = {worksheet_url}")

        # checks if table for this month exists, otherwise create it
        table_url = self.get_table_url(worksheet_url)
        print(f"Table URL FINAL = {table_url}")

        # delete Sheet1
        if new_book == True:
            self.deleteSheet1(worksheets_url)

        return table_url

    def upload_data(self, job):

        body = {
            "values": job.generate_date_data() # this function is from mc_details class
        }
        
        self.write_to_excel(body)
        print("Data uploaded successfully")

   
    def write_to_excel(self, json):

        # write to file
        write_to_table_url = f"{self.table_url}/rows"

        @delay_decorator("Failed to upload data.")
        def _write_to_excel():
            response = requests.post(write_to_table_url, headers=self.headers, json = json)
            print(response.json())
            return response
        
        _write_to_excel()
        

    def add_table(self, worksheet_url, name):

        # ADD TABLE HEADERS
        @delay_decorator("Table headers could not be initialised.", retries = 10)
        def _add_table_headers():
            table_headers_url = f"{worksheet_url}/range(address='A1:C1')"

            header_values = {
                "values": [["Date", "Name", "Department"]]
            }

            response = requests.patch(table_headers_url, headers=self.headers, json=header_values)
            return response

        # ADD TABLE
        @delay_decorator("Table itself could not be initialised.", retries = 10)
        def _add_table():
            add_table_url = f"{worksheet_url}/tables/add"

            body = {
                "address": "A1:C1",
                "hasHeaders": True,
            }

            response = requests.post(add_table_url, headers=self.headers, json=body)
            return response

        # CHANGE TABLE NAME
        @delay_decorator("Table name could not be changed. There might be tables with duplicate names.", retries = 10)
        def _change_tablename(table_id):
            change_tablename_url = f"{worksheet_url}/tables/{table_id}"

            table_options = {
                "name": name
            }

            response = requests.patch(change_tablename_url, headers=self.headers, json=table_options)
            return response
        
        # see delay_decorator for more info
        _add_table_headers()
        print("table headers added successfully")
        response = _add_table()
        table_id = response.json()['id'] 
        print("tables created successfully")
        _change_tablename(table_id)
        print("tables renamed successfully")

        # return table

        return table_id

    def get_table_url(self, worksheet_url):

        tables_url = f"{worksheet_url}/tables"
        
        @delay_decorator("Could not get the tables")
        def get_tables():

            response = requests.get(url=tables_url, headers=self.headers)
            return response
        
        response = get_tables()
        print("tables queried successfully")

        table_ids = {table_obj["name"]: table_obj['id'] for table_obj in response.json()['value']}
        
        if cur_datetime("%B") not in table_ids.keys():
            table_id = self.add_table(worksheet_url, cur_datetime("%B"))
        # if table found, get the id
        else:
            table_id = table_ids[f"{cur_datetime('%B')}"]
            
        table_url = f"{tables_url}/{table_id}"

        return table_url

    def add_worksheet(self, worksheets_url, name):

        @delay_decorator("Sheet failed to add.")
        def _add_worksheet():
            body = {
                "name": name
            }

            # add the worksheet
            response = requests.post(url=f"{worksheets_url}/add", headers=self.headers, json=body)
            return response
        
        response = _add_worksheet()
        print("sheet added successfully")
        worksheet_id = response.json()['id']

        return worksheet_id

    def get_sheet_url(self, worksheets_url):

        @delay_decorator("Failed to get sheets")
        def _get_sheet_url():

            # get the worksheet names
            response = requests.get(url=worksheets_url, headers=self.headers)
            return response
        
        response = _get_sheet_url()
        print("sheets queried successfully")

        ws_ids = {sheet_obj["name"]: sheet_obj['id'] for sheet_obj in response.json()['value']}
        
        if cur_datetime('%B') not in ws_ids.keys():
            ws_id = self.add_worksheet(worksheets_url, cur_datetime("%B"))
        # if ws found, get the id
        else:
            ws_id = ws_ids[f"{cur_datetime('%B')}"]
            
        worksheet_url = f"{worksheets_url}/{ws_id}"

        return worksheet_url

    def create_book(self):

        @delay_decorator("Failed to upload file")
        def _create_book():
            # uploads the file
            response = requests.put(self.create_book_url, headers=self.headers, data=file_data)
            return response

        with open(self.template_path, 'rb') as file_data:
            response = _create_book()
        

        print("book created successfully")
        book_id = response.json()['id']
        return book_id
        

    def deleteSheet1(self, worksheets_url):

        del_sheet1_url = worksheets_url + "/Sheet1"

        @delay_decorator("Failed to delete Sheet1")
        def _deleteSheet1():
            # delete the sheet
            response = requests.delete(del_sheet1_url, headers=self.headers)
            return response
        
        _deleteSheet1()
        print("Sheet1 deleted successfully")


    def get_sheets_url(self):
        @delay_decorator("Could not check if book exists")
        def _get_sheets_url():
            response = requests.get(url=self.query_book_url, headers=self.headers) 
            return response
        
        new_book = False

        response = _get_sheets_url()
        book_name = response.json()['value']
        if not book_name:
            new_book = True
            book_id = self.create_book()
        else:
            book_id = book_name[0]['id']

        worksheets_url = self.drive_url + f"/items/{book_id}/workbook/worksheets"
        return [worksheets_url, new_book]


    def send_message_to_principal(self, client):
        
        p_name, p_number = User.get_principal()

        response = requests.get(url=f"{self.table_url}/rows?", headers=self.headers)
        mc_arrs = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
        mc_table = pd.DataFrame(data = mc_arrs, columns=["date", "name", "dept"])
        # filter by today
        date_today = datetime.strftime(datetime.now(), "%d/%m/%Y")
        mc_today = mc_table.loc[mc_table['date'] == date_today]
        
        #groupby
        mc_today_by_dept = mc_today.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))

        # convert to a dictionary where the dept is the key
        dept_aggs = mc_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()

        dept_order = ('ICT', 'Finance', 'Voc Ed', 'Lower Pri', 'Upper Pri', 'Allied Professionals', 'HR')

        content_variables = {
            '1': p_name,
            '2': date_today,
            '17': total
        }
        
        # get values
        # message = []
        total = 0
        # if len(mc_today_by_dept) == 0:
        #     message += "All staff are present today\r\r"
        if len(mc_today_by_dept) != 0:
            count = 3
            for dept in dept_order:
                found = False
                if dept in dept_aggs:
                    content_variables[str(count)] = dept_aggs['dept'][1]  # names
                    content_variables[str(count + 1)] = str(dept_aggs['dept'][0])  # number of names
                    found = True
                    break  # Exit the loop as we found the department

                if not found:  # If department was not in message, add default values
                    content_variables[str(count)] = "NIL"
                    content_variables[str(count + 1)] = '0'  # number of names

                count += 2

        # print(type(message))
        # print(type(date_today))

        content_variables = json.dumps(content_variables)
        
        message = client.messages.create(
            to=str(p_number),
            from_=os.environ.get("MESSAGING_SERVICE_SID"),
            content_sid=os.environ.get("MC_DAILY_SID"),
            content_variables=content_variables,
            # status_callback=os.environ.get("CALLBACK_URL")
        )

if __name__ == "__main__":
    from app import app
    from models.chatbot import client
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=env_path)
    manager = SpreadsheetManager()
    try:
        with app.app_context():
            manager.send_message_to_principal(client)
    except AzureSyncError as e:
        print(e.message)
        # raise ReplyError("I'm sorry, something went wrong with the code, please check with ICT")