from datetime import datetime, timedelta, time
import os
import requests
from dotenv import load_dotenv
import pandas as pd
import json

import logging
import traceback


from ..utils import generate_header, delay_decorator, AzureSyncError
from utilities import current_sg_time
from models.users import User
from logs.config import setup_logger

class SpreadsheetManager:

    def __init__(self, mmyy=None, user=None, logger=None):
        self.template_path = os.path.join(os.path.dirname(__file__), 'excel_files', 'mc_template.xlsx')
        self.drive_url = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}"
        self.folder_url = self.drive_url + f"/items/{os.environ.get('FOLDER_ID')}"
        if mmyy:
            self.mmyy = mmyy
            self.month, self.year = mmyy.split("-")
        else:
            self.month = current_sg_time().strftime('%B')
            self.year = current_sg_time().year
            self.mmyy = f"{self.month}-{self.year}"

        self.user = user if user else None

        self.logger = logger if logger else setup_logger('az.mc.spreadsheetmanager')

        self.logger.info(f"drive_url: {self.drive_url}, folder_url = {self.folder_url}")

    @property
    def query_book_url(self):
        return self.folder_url + f"/children?$filter=name eq '{self.year}.xlsx'"
    
    @property
    def create_book_url(self):
        return self.folder_url + f":/{self.year}.xlsx:/content"

    @property
    def headers(self):
        # read the token from the file
        return generate_header()
    
    @property
    def table_url(self):
        '''
        This property can call every method below it that creates a new book, adds a worksheet and a table, and delete the original sheet. It abstracts the creation of the current month table into a single property
        
        The final path is in the form https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{book_id}/workbook/worksheets/{ws_id}/tables/{table_id}
        '''
        # get the workbook for this year
        # self.logger.info(self.query_book_url)
        # self.logger.info(self.headers)

        if os.path.exists('/home/app/web/logs/table_urls.json') and os.path.getsize('/home/app/web/logs/table_urls.json') > 0:
            mode = 'r+'
        else:
            mode = 'w+'

        with open('/home/app/web/logs/table_urls.json', mode) as file:
            try:
                table_url_dict = json.loads(file.read())
                table_url = table_url_dict.get(self.mmyy)
                if table_url:
                    self.logger.info("URL FOUND IN CACHE")
                    return table_url
            except json.JSONDecodeError:
                self.logger.info(traceback.format_exc())
                table_url_dict = {}
                file.write(json.dumps(table_url_dict))

        worksheets_url, new_book = self.get_sheets_url()

        # checks if sheet for this month exists, otherwise create it
        worksheet_url = self.get_sheet_url(worksheets_url)
        self.logger.info(f"Worksheet URL FINAL = {worksheet_url}")

        # checks if table for this month exists, otherwise create it
        table_url = self.get_table_url(worksheet_url)
        self.logger.info(f"Table URL FINAL = {table_url}")

        # delete Sheet1
        if new_book == True:
            self.deleteSheet1(worksheets_url)

        with open("/home/app/web/logs/table_urls.json", 'r+') as file:
            file.seek(0)
            table_url_dict[self.mmyy] = table_url
            file.write(json.dumps(table_url_dict, indent=4))
            file.truncate()

        return table_url

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
    
    def get_sheet_url(self, worksheets_url):

        @delay_decorator("Failed to get sheets")
        def _get_sheet_url():

            # get the worksheet names
            response = requests.get(url=worksheets_url, headers=self.headers)
            return response
        
        response = _get_sheet_url()
        self.logger.info("sheets queried successfully")

        ws_ids = {sheet_obj["name"]: sheet_obj['id'] for sheet_obj in response.json()['value']}
        
        if self.month not in ws_ids.keys():
            ws_id = self.add_worksheet(worksheets_url, self.month)
        # if ws found, get the id
        else:
            ws_id = ws_ids[self.month]
            
        worksheet_url = f"{worksheets_url}/{ws_id}"

        return worksheet_url
    
    def get_table_url(self, worksheet_url):

        tables_url = f"{worksheet_url}/tables"
        
        @delay_decorator("Could not get the tables")
        def get_tables():

            response = requests.get(url=tables_url, headers=self.headers)
            return response
        
        response = get_tables()
        self.logger.info("tables queried successfully")

        table_ids = {table_obj["name"]: table_obj['id'] for table_obj in response.json()['value']}
        
        if self.month not in table_ids.keys():
            table_id = self.add_table(worksheet_url, self.month)
        # if table found, get the id
        else:
            table_id = table_ids[self.month]
            
        table_url = f"{tables_url}/{table_id}"

        return table_url
    

    #######################################
    # CREATING IF NOT EXISTS
    #######################################

    def create_book(self):

        @delay_decorator("Failed to upload file")
        def _create_book():
            # uploads the file
            response = requests.put(self.create_book_url, headers=self.headers, data=file_data)
            return response

        with open(self.template_path, 'rb') as file_data:
            response = _create_book()
        

        self.logger.info("book created successfully")
        book_id = response.json()['id']
        self.logger.info(book_id)
        return book_id
    
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
        self.logger.info("sheet added successfully")
        worksheet_id = response.json()['id']

        return worksheet_id

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
        self.logger.info("table headers added successfully")
        response = _add_table()
        table_id = response.json()['id']
        self.logger.info("tables created successfully")
        _change_tablename(table_id)
        self.logger.info("tables renamed successfully")

        # return table

        return table_id
    
    #######################################
    # DELETE THE NEWLY CREATED SHEET
    #######################################
    
    def deleteSheet1(self, worksheets_url):

        del_sheet1_url = worksheets_url + "/Sheet1"

        @delay_decorator("Failed to delete Sheet1")
        def _deleteSheet1():
            # delete the sheet
            response = requests.delete(del_sheet1_url, headers=self.headers)
            return response
        
        _deleteSheet1()
        self.logger.info("Sheet1 deleted successfully")
        



    #######################################
    # DATA VALIDATION
    #######################################
        
    def find_current_dates(self):
        '''returns the current dates in a format %d/%m/%Y (to be stored as JSON in psql), and returns duplicates and non duplicates as date objects to be passed to utilities print_all_dates function)'''
        get_rows_url = f"{self.table_url}/rows"

        self.logger.info(f"get rows url: {get_rows_url}")

        @delay_decorator("Table itself could not be initialised.", retries = 10)
        def _find_current_dates(url):
            response = requests.get(url=url, headers=self.headers)
            return response
        

        response = _find_current_dates(get_rows_url)
            
        current_details_list = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]

        self.logger.info(current_details_list[:5])
        current_details_df = pd.DataFrame(data = current_details_list, columns = ["date", "name", "dept"])

        self.logger.info(current_details_df.head())

        current_details_df['date'] = pd.to_datetime(current_details_df['date'], format='%d/%m/%Y')
        current_details_df['date'] = current_details_df['date'].dt.date

        time_now = current_sg_time()

        if time_now > current_sg_time(hour_offset = 8):
            mask = ((current_details_df["name"] == self.user.name) & (current_details_df["date"] > time_now.date()))
        else:
            mask = ((current_details_df["name"] == self.user.name) & (current_details_df["date"] >= time_now.date()))

        current_dates = current_details_df.loc[mask, "date"]

        return current_dates    
    
    
    def get_unique_current_dates(self):

        current_dates = self.find_current_dates()

        current_dates = current_dates.unique()

        self.logger.info(f"Current unique dates: {current_dates}")

        return current_dates
    

    def check_duplicate_dates(self, dates_list):

        self.logger.info(f"Dates list: {dates_list}, name: {self.user.name}")

        current_mc_dates = self.get_unique_current_dates()

        # dates_in_df = set(current_details_df["date"])
        duplicates_array = [date for date in dates_list if date in current_mc_dates]
        non_duplicates_array = [date for date in dates_list if date not in current_mc_dates]


        return (duplicates_array, non_duplicates_array)


    #######################################
    # UPLOADING DATA
    #######################################
    
    def upload_data(self, dates_list):

        modified_dates_list = [f"'{date}" for date in dates_list]

        body = {
            "values": [[date, self.user.name, self.user.dept] for date in modified_dates_list]
        }
        
        self.write_to_excel(body)
        self.logger.info("Data uploaded successfully")

   
    def write_to_excel(self, json):

        # write to file
        write_to_table_url = f"{self.table_url}/rows"

        @delay_decorator("Failed to upload data.")
        def _write_to_excel():
            response = requests.post(write_to_table_url, headers=self.headers, json = json)
            self.logger.info(response.json())
            return response
        
        _write_to_excel()

    ####################################
    # DELETING DATA
    ####################################

    def delete_data(self, dates_list):

        dates_list = [datetime.strptime(date, "%d/%m/%Y").date() for date in dates_list]

        current_dates = self.find_current_dates()
        # self.logger.info(f"current dates: {current_dates}")

        dates_to_del = current_dates.loc[current_dates.isin(dates_list)]
        # self.logger.info(f"dates to del df: {dates_to_del}")

        indexes = dates_to_del.index.tolist()
        # self.logger.info(f"indexes to delete: {indexes}")

        self.delete_from_excel(indexes)

        del_dates = dates_to_del.tolist()
        del_dates = [datetime.strftime(date, "%d/%m/%Y") for date in del_dates] # old dates are not removed
        # self.logger.info(f"ok dates: {ok_dates}")

        self.logger.info("Data deleted successfully")
        return del_dates

   
    def delete_from_excel(self, indexes):

        # delete from file
        remove_from_table_url = f"{self.table_url}/rows/"

        @delay_decorator("Failed to delete data.")
        def _delete_from_excel(index):
            remove_index_url = remove_from_table_url + f"ItemAt(index={str(index)})"
            self.logger.info(remove_index_url)
            response = requests.delete(remove_index_url, headers=self.headers)
            return response
        
        sorted_indexes = sorted(indexes, reverse=True)
        for index in sorted_indexes:
            _delete_from_excel(index)


    #####################################
    # SENDING MESSAGE TO PRINCIPAL
    #####################################

    def send_message_to_principal(self, client):

        response = requests.get(url=f"{self.table_url}/rows?", headers=self.headers)
        # self.logger.info(response.text)
        mc_arrs = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
        mc_table = pd.DataFrame(data = mc_arrs, columns=["date", "name", "dept"])
        # filter by today
        date_today = current_sg_time("%d/%m/%Y")
        mc_today = mc_table.loc[mc_table['date'] == date_today]

        content_variables = {
                '2': date_today
            }

        all_present = False
        
        if len(mc_today) == 0:
            all_present = True
        
        if not len(mc_today) == 0:

            #groupby
            mc_today_by_dept = mc_today.groupby("dept").agg(total_by_dept = ("name", "count"), names = ("name", lambda x: ', '.join(x)))

            # convert to a dictionary where the dept is the key
            dept_aggs = mc_today_by_dept.apply(lambda x: [x.total_by_dept, x.names], axis=1).to_dict()

            # self.logger.info(dept_aggs)

            dept_order = ('ICT', 'Finance', 'Voc Ed', 'Lower Pri', 'Upper Pri', 'Allied Professionals', 'HR')

            total = 0

            count = 3
            for dept in dept_order:
                if dept in dept_aggs:
                    content_variables[str(count)] = dept_aggs[dept][1]  # names
                    content_variables[str(count + 1)] = str(dept_aggs[dept][0])  # number of names
                    total += dept_aggs[dept][0]
                    count += 2
                    continue

                content_variables[str(count)] = "NIL"
                content_variables[str(count + 1)] = '0'  # number of names
                count += 2

            content_variables['17'] = str(total)

            # self.logger.info(type(message))
            # self.logger.info(type(date_today))
                    
            # self.logger.info(content_variables)

        for global_admin in User.get_global_admins():

            # self.logger.info(f"{p_name}, {p_number}")

            new_content_variables = content_variables
            new_content_variables['1'] = global_admin.name

            content_variables = json.dumps(new_content_variables)
            
            
            client.messages.create(
                to=str(global_admin.sg_number),
                from_=os.environ.get("MESSAGING_SERVICE_SID"),
                content_sid=os.environ.get("SEND_MESSAGE_TO_LEADERS_SID") if all_present else os.environ.get("SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID"),
                content_variables=new_content_variables,
                # status_callback=os.environ.get("CALLBACK_URL")
            )

if __name__ == "__main__":
    from app import app
    from config import client

    logger = setup_logger('az.mc.report', 'daily_mc_report.log')

    env_path = "/home/app/web/.env"
    load_dotenv(dotenv_path=env_path)
    manager = SpreadsheetManager(logger=logger)

    try:
        with app.app_context():
            manager.send_message_to_principal(client)

    except AzureSyncError as e:

        logger.info(e.message)
        # raise ReplyError("I'm sorry, something went wrong with the code, please check with ICT")

    except Exception as e:

        logger.info(traceback.format_exc())