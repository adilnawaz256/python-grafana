import argparse
import sys
import json
from db_connection import DBManager
from data_generator import DataGenerator
from db_pusher import DBPusher
from scheduler import CronSchedulerDaemon

def command_inspect(config_path):
    """Inspects database schema and table statistics cleanly."""
    print("=== Database Connection & Schema Inspection ===")
    db = DBManager(config_path)
    version = db.test_connection()
    print(f"PostgreSQL Version: {version}\n")

    conn = db.get_connection()
    tables = []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema, table_name 
                FROM information_schema.tables 
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name;
            """)
            tables = cur.fetchall()
    finally:
        db.release_connection(conn)

    for schema, table in tables:
        conn = db.get_connection()
        count = 0
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}";')
                count = cur.fetchone()[0]
        finally:
            db.release_connection(conn)

        cols = db.get_table_schema(table, schema)
        latest = db.get_latest_record(table, schema)
        
        print(f"Table: {schema}.{table} | Total Rows: {count} | Columns Count: {len(cols)}")
        if latest:
            sample_date = latest.get("date") or latest.get("timestamp") or "N/A"
            print(f"  Latest Record Date: {sample_date}")
        print("-" * 60)

    db.close_all()

def command_generate_once(config_path, count, table_name):
    """Generates and pushes N records immediately."""
    print(f"=== Single Batch Generation (count={count}, table={table_name}) ===")
    db = DBManager(config_path)
    gen = DataGenerator(db)
    pusher = DBPusher(db)

    try:
        records = gen.generate_batch(table_name=table_name, count=count)
        inserted = pusher.insert_records(table_name=table_name, records=records)
        print(f"Success! Inserted {inserted} record(s) into '{table_name}'.")
        for idx, rec in enumerate(records):
            print(f" Record #{idx+1} -> Date: {rec.get('date')} | affected_sites: {rec.get('affected_sites')} | availability: {rec.get('end_to_end_availability')}")
    finally:
        db.close_all()

def command_start_daemon(config_path):
    """Starts continuous scheduled cron generator daemon."""
    print("=== Starting Cron Scheduler Daemon ===")
    daemon = CronSchedulerDaemon(config_path)
    daemon.start()

def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Telemetry Data Generator & Cron Scheduler")
    parser.add_argument("--config", default="config.yaml", help="Path to config file (default: config.yaml)")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Inspect command
    subparsers.add_parser("inspect", help="Inspect DB connection, schemas, and row counts")

    # Generate-once command
    gen_parser = subparsers.add_parser("generate-once", help="Generate and insert a single batch of records")
    gen_parser.add_argument("--count", type=int, default=1, help="Number of records to generate (default: 1)")
    gen_parser.add_argument("--table", default="data_sample", help="Target table name (default: data_sample)")

    # Start-daemon command
    subparsers.add_parser("start-daemon", help="Start continuous scheduled cron daemon")

    args = parser.parse_args()

    if args.command == "inspect":
        command_inspect(args.config)
    elif args.command == "generate-once":
        command_generate_once(args.config, args.count, args.table)
    elif args.command == "start-daemon":
        command_start_daemon(args.config)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
