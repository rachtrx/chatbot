import openpyxl
import pandas as pd
import sqlite3

def connect_to_db(func):
    def wrapper(*args, **kwargs):
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        result = func(cursor, *args, **kwargs)
        conn.commit()
        conn.close()
        return result
    return wrapper   

@connect_to_db
def main(cursor):
    # Create a users table
    cursor.execute('''CREATE TABLE users (name TEXT UNIQUE, number INTEGER UNIQUE, email TEXT UNIQUE, reporting_officer TEXT, hod TEXT)''')

@connect_to_db
def get_name(cursor, phone):
    cursor.execute('SELECT name FROM users WHERE number = ?', (phone,))
    return None if name is None else name[0]
    
@connect_to_db
def sync(cursor, file):

    sh_users = pd.read_excel(file)
    sh_users.sort_values(by="name", inplace=True)

    cursor.execute('SELECT * FROM users ORDER BY name ASC')
    db_users = cursor.fetchall()

    column_names = [description[0] for description in cursor.description]
    
    '''from chatGPT:
        description[0]: The name of the column (a string).
        description[1]: The type of the column, if known; otherwise, it returns None. This type is typically provided by the underlying database interface.
        description[2]: The display size of the column (in characters) for variable-length columns; otherwise, it returns None.
        description[3]: The internal size of the column (in bytes).
        description[4]: The precision of the column for numeric columns.
        description[5]: The scale of the column for numeric columns.
        description[6]: Whether the column can contain NULL (returns True or False).
        description[7]: Additional column-specific information.'''

    db_users = pd.DataFrame(db_users, columns=column_names)
    
    # db_users and sh_users are now dataframes

    exact_match = sh_users.equals(db_users)

    if not exact_match:
        # create 2 dataframes to compare
        old_users = pd.merge(sh_users, db_users, how="outer", indicator=True).query('_merge == "right_only"').drop(columns='_merge')
        new_users = pd.merge(sh_users, db_users, how="outer", indicator=True).query('_merge == "left_only"').drop(columns='_merge')

        old_users_tuples = [tuple(old_user) for old_user in old_users.values]
        new_users_tuples = [tuple(new_user) for new_user in new_users.values]

        for name, number, email, reporting_officer, hod in old_users_tuples:
            cursor.execute('DELETE FROM users WHERE name = ?', (name,))
            
        for name, number, email, reporting_officer, hod in new_users_tuples:
            cursor.execute('INSERT INTO users (name, number, email, reporting_officer, hod) VALUES (?, ?, ?, ?, ?)', (name, number, email, reporting_officer, hod))


if __name__ == "__main__":
    main()