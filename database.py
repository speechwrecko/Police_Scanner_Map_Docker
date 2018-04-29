import sqlite3
import csv

class database:

    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)


    def InsertRow(self, tablename, row):
        cursor2 = self.db.cursor()
        cursor2.execute(f'insert into {tablename} values (?,?,?,?,?,?)', (row[0], row[1], row[2], row[3], row[4], row[5]))
        self.db.commit()
        return

    def GetRows(self, tablename, query_param1, query_param2):
        cursor2 = self.db.cursor()
        cursor2.execute(f'SELECT * FROM {tablename} WHERE {query_param1} AND {query_param2}')
        rows = cursor2.fetchall()
        return rows


    def ExportCSV(self, tablename):
        csv_cursor = self.db.cursor()
        csv_cursor.execute(f'SELECT * FROM {tablename}')
        with open('export.csv', 'w', newline='') as out_csv_file:
            csv_out = csv.writer(out_csv_file)
            # write header
            csv_out.writerow([d[0] for d in csv_cursor.description])
            # write data
            for result in csv_cursor:
                csv_out.writerow(result)

        out_csv_file.close()
        return out_csv_file