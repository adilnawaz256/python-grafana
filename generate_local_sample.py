import json
import csv
from db_connection import DBManager
from data_generator import DataGenerator

def generate_local_sample(count=10, json_file="sample_10_records.json", csv_file="sample_10_records.csv"):
    print(f"=== Generating {count} Local Sample Records (Dry Run - No DB Insertion) ===")
    db = DBManager()
    gen = DataGenerator(db)

    try:
        # Generate count sample rows using Excel Upper/Lower limits
        records = gen.generate_batch(table_name="data_sample", count=count)

        # Convert datetime objects to string format for JSON serialization
        json_records = []
        for r in records:
            r_copy = r.copy()
            if "date" in r_copy and r_copy["date"]:
                r_copy["date"] = str(r_copy["date"])
            json_records.append(r_copy)

        # 1. Save to local JSON file
        with open(json_file, "w") as f:
            json.dump(json_records, f, indent=2)
        print(f" Saved local sample to JSON: {json_file}")

        # 2. Save to local CSV file
        if records:
            keys = list(records[0].keys())
            with open(csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for r in records:
                    r_copy = r.copy()
                    if "date" in r_copy and r_copy["date"]:
                        r_copy["date"] = str(r_copy["date"])
                    writer.writerow(r_copy)
            print(f" Saved local sample to CSV: {csv_file}\n")

        # Print preview of key KPI columns for inspection
        print("-" * 110)
        print(f"{'#':<3} | {'Date':<26} | {'Latency':<8} | {'VoLTE CSSR':<10} | {'Packet Loss':<11} | {'E2E Avail':<10} | {'Sites Down':<10}")
        print("-" * 110)
        for idx, r in enumerate(records):
            print(f"{idx+1:<3} | {str(r.get('date')):<26} | {str(r.get('latency'))+'ms':<8} | {str(r.get('volte_cssr'))+'%':<10} | {str(r.get('packet_loss'))+'%':<11} | {str(r.get('end_to_end_availability'))+'%':<10} | {str(r.get('site_down')):<10}")
        print("-" * 110)

    finally:
        db.close_all()

if __name__ == "__main__":
    generate_local_sample(10)
