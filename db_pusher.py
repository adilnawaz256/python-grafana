import logging
import psycopg2
from psycopg2 import extras
from db_connection import DBManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DBPusher")

class DBPusher:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager

    def insert_records(self, table_name: str, records: list, schema: str = "public"):
        """
        Inserts a list of dictionary records into PostgreSQL table using execute_values.
        Ensures transaction atomicity and proper connection release.
        """
        if not records:
            logger.info(f"No records provided for table {schema}.{table_name}.")
            return 0

        # Extract column names from first record dictionary keys
        columns = list(records[0].keys())
        quoted_columns = [f'"{col}"' for col in columns]
        col_str = ", ".join(quoted_columns)

        # Prepare tuple values
        values_tuples = [
            tuple(rec[col] for col in columns)
            for rec in records
        ]

        sql = f'INSERT INTO "{schema}"."{table_name}" ({col_str}) VALUES %s;'

        conn = self.db.get_connection()
        inserted_count = 0
        try:
            with conn.cursor() as cur:
                extras.execute_values(cur, sql, values_tuples, page_size=100)
                conn.commit()
                inserted_count = len(records)
                logger.info(f"Successfully inserted {inserted_count} record(s) into {schema}.{table_name}.")
                return inserted_count
        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting records into {schema}.{table_name}: {e}")
            raise
        finally:
            self.db.release_connection(conn)

if __name__ == "__main__":
    from data_generator import DataGenerator
    db = DBManager()
    gen = DataGenerator(db)
    pusher = DBPusher(db)
    
    test_rows = gen.generate_batch("data_sample", count=1)
    print("Testing record insert...")
    pusher.insert_records("data_sample", test_rows)
    db.close_all()
