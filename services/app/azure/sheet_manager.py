from datetime import datetime, timedelta, time
import os
import requests
import numpy as np
import pandas as pd
import json

import logging
import traceback

from azure.utils import generate_header, delay_decorator
from utilities import current_sg_time, get_latest_date_past_8am
from logs.config import setup_logger
import calendar

class SpreadsheetManager:

    def __init__(self, mmyy=None, user=None, token=None, dev=False):
        self.template_path = '/home/app/web/excel_files/mc_template.xlsx'
        self.drive_url = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}"
        self.folder_url = self.drive_url + f"/items/{os.environ.get('FOLDER_ID')}"
        if mmyy:
            self.month, self.year = mmyy
            self.month = calendar.month_name[self.month]
        else:
            self.month = current_sg_time().strftime('%B')
            self.year = current_sg_time().year
        self.mmyy = f"{self.month}-{self.year}"

        self.user = user if user else None
        self.dev = dev

        if not dev:
            self.logger = setup_logger('az.leave.spreadsheetmanager')
        else:
            self.logger = setup_logger('app', 'test', '.')
        self.logger.info(f"drive_url: {self.drive_url}, folder_url = {self.folder_url}")
        self.headers = generate_header(token)

    @property
    def query_book_url(self):
        return self.folder_url + f"/children?$filter=name eq '{self.year}.xlsx'"
    
    @property
    def create_book_url(self):
        return self.folder_url + f":/{self.year}.xlsx:/content"
    
    @property
    def table_url(self):
        '''
        This property can call every method below it that creates a new book, adds a worksheet and a table, and delete the original sheet. It abstracts the creation of the current month table into a single property
        
        The final path is in the form https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{book_id}/workbook/worksheets/{ws_id}/tables/{table_id}
        '''
        # get the workbook for this year
        # self.logger.info(self.query_book_url)
        # self.logger.info(self.headers)

        if not self.dev:
            url_cache='/home/app/web/logs/table_urls.json'
        else:
            url_cache='table_urls.json'

        if os.path.exists(url_cache) and os.path.getsize(url_cache) > 0:
            mode = 'r+'
        else:
            mode = 'w+'

        with open(url_cache, mode) as file:
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

        with open(url_cache, 'r+') as file:
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
            table_headers_url = f"{worksheet_url}/range(address='A1:E1')"

            header_values = {
                "values": [["id", "Date", "Name", "Department", "Type"]]
            }

            response = requests.patch(table_headers_url, headers=self.headers, json=header_values)
            return response

        # ADD TABLE
        @delay_decorator("Table itself could not be initialised.", retries = 10)
        def _add_table():
            add_table_url = f"{worksheet_url}/tables/add"

            body = {
                "address": "A1:E1",
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
        
    def find_all_dates(self):
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
        current_details_df = pd.DataFrame(data = current_details_list, columns = ["record_id", "date", "name", "dept", "leave_type"])

        self.logger.info(current_details_df.head())
        current_details_df['date'] = current_details_df['date'].str.strip()
        current_details_df.replace('', np.nan, inplace=True)
        empty_date_mask = current_details_df['date'].isna()
        current_details_df['date'] = current_details_df['date'].astype('object')
        current_details_df.loc[~empty_date_mask, 'date'] = pd.to_datetime(current_details_df.loc[~empty_date_mask, 'date'], format='%d/%m/%Y').dt.date
        current_details_df = current_details_df.reset_index(drop=False).rename(columns={'index': 'az_index'})
        current_details_df = current_details_df.astype({"record_id": str, "name": str, "dept": str, "leave_type": str, "az_index": int})
        logging.info(current_details_df)

        self.logger.info(f"DATES IN FIND CURRENT DATES: {current_details_df.date}")

        return current_details_df
    
    
    def get_unique_current_dates(self):

        current_dates = self.find_current_dates()

        current_dates = current_dates.unique()

        self.logger.info(f"Current unique dates: {current_dates}")

        return current_dates
    

    def check_duplicate_dates(self, dates_list):

        self.logger.info(f"Dates list: {dates_list}, name: {self.user.name}")

        current_leave_dates = self.get_unique_current_dates()

        # dates_in_df = set(current_details_df["date"])
        duplicates_array = [date for date in dates_list if date in current_leave_dates]
        non_duplicates_array = [date for date in dates_list if date not in current_leave_dates]


        return (duplicates_array, non_duplicates_array)


    #######################################
    # UPLOADING DATA
    #######################################
    
    def upload_data(self, data):
        self.write_to_excel({"values": data})
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

    def delete_data(self, indexes):

        self.delete_from_excel(indexes)
        # self.logger.info(f"ok dates: {ok_dates}")

        self.logger.info("Data deleted successfully")
        return
   
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

