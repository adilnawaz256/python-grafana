import datetime
import logging
import random
import numpy as np
from db_connection import DBManager
from kpi_limits import parse_limit_rules

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DataGenerator")

class DataGenerator:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager
        self.config = db_manager.config
        self.gen_cfg = self.config.get("generator_settings", {})
        self.noise_factor = self.gen_cfg.get("noise_factor", 0.05)
        self.advance_timestamp = self.gen_cfg.get("advance_timestamp_from_latest", True)
        self.timestamp_step_seconds = self.gen_cfg.get("timestamp_step_seconds", 60)
        self._schema_cache = {}
        self._stats_cache = {}
        self._pk_counters = {}
        
        # Load upper and lower limit rules from Excel
        self.kpi_rules = parse_limit_rules()
        logger.info(f"Loaded {len(self.kpi_rules)} KPI upper/lower limit rules from Excel.")

    def get_cached_schema(self, table_name: str, schema: str = "public"):
        key = f"{schema}.{table_name}"
        if key not in self._schema_cache:
            self._schema_cache[key] = self.db.get_table_schema(table_name, schema)
        return self._schema_cache[key]

    def get_cached_stats(self, table_name: str, schema: str = "public"):
        key = f"{schema}.{table_name}"
        if key not in self._stats_cache:
            logger.info(f"Caching stats for {key}...")
            self._stats_cache[key] = self.db.get_table_stats(table_name, schema)
        return self._stats_cache[key]

    def get_next_pk_value(self, table_name: str, col_name: str = "id", schema: str = "public"):
        """Returns next incrementing ID for primary key columns."""
        key = f"{schema}.{table_name}.{col_name}"
        if key not in self._pk_counters:
            conn = self.db.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT MAX("{col_name}") FROM "{schema}"."{table_name}";')
                    r = cur.fetchone()
                    max_v = r[0] if r and r[0] is not None else 0
                    self._pk_counters[key] = int(max_v)
            finally:
                self.db.release_connection(conn)
        
        self._pk_counters[key] += 1
        return self._pk_counters[key]

    def generate_row(self, table_name: str, schema: str = "public", base_datetime: datetime.datetime = None, latest_row: dict = None, include_pk: bool = True):
        """
        Dynamically generates a single record for table_name based on cached introspection statistics
        and upper/lower limit threshold rules from upper-lower limit for kpis.xlsx.
        Includes ALL columns (including PK id).
        """
        schema_info = self.get_cached_schema(table_name, schema)
        stats = self.get_cached_stats(table_name, schema)

        if latest_row is None:
            latest_row = self.db.get_latest_record(table_name, schema) or {}

        row_data = {}

        for col in schema_info:
            col_name = col["column_name"]
            data_type = col["data_type"].lower()

            # Handle primary key / ID column
            if col["is_primary_key"] or col_name == "id":
                if include_pk:
                    row_data[col_name] = self.get_next_pk_value(table_name, col_name, schema)
                continue

            # 1. Date / Timestamp handling
            if "timestamp" in data_type or "date" in data_type:
                if base_datetime:
                    ts = base_datetime
                elif self.advance_timestamp and latest_row and col_name in latest_row and latest_row[col_name]:
                    last_ts = latest_row[col_name]
                    if isinstance(last_ts, str):
                        last_ts = datetime.datetime.fromisoformat(last_ts)
                    ts = last_ts + datetime.timedelta(seconds=self.timestamp_step_seconds)
                else:
                    ts = datetime.datetime.now()
                row_data[col_name] = ts

            # 2. Categorical / Text handling
            elif data_type in ("text", "character varying", "character"):
                col_stat = stats.get(col_name, {})
                choices = col_stat.get("choices", ["Active/Active", "Active"])
                if latest_row and col_name in latest_row and latest_row[col_name] is not None:
                    if random.random() < 0.90:
                        val = latest_row[col_name]
                    else:
                        val = random.choice(choices)
                else:
                    val = random.choice(choices)
                row_data[col_name] = val

            # 3. Numeric handling (Double precision, Bigint, Integer, Numeric)
            elif data_type in ("double precision", "real", "bigint", "integer", "numeric", "smallint"):
                rule = self.kpi_rules.get(col_name, {})
                healthy_range = rule.get("healthy_range")
                warning_range = rule.get("warning_range")

                if healthy_range and healthy_range[0] is not None and healthy_range[1] is not None:
                    if warning_range and warning_range[0] is not None and warning_range[1] is not None and random.random() < 0.05:
                        val = random.uniform(warning_range[0], warning_range[1])
                    else:
                        if healthy_range[0] == healthy_range[1]:
                            val = healthy_range[0]
                        else:
                            val = random.uniform(healthy_range[0], healthy_range[1])
                else:
                    col_stat = stats.get(col_name, {})
                    min_val = col_stat.get("min", 0.0)
                    max_val = col_stat.get("max", 100.0)
                    avg_val = col_stat.get("avg", 50.0)
                    std_val = col_stat.get("stddev", 1.0)

                    if latest_row and col_name in latest_row and latest_row[col_name] is not None:
                        base_val = float(latest_row[col_name])
                    else:
                        base_val = avg_val

                    std_adj = max(std_val * self.noise_factor, 0.05)
                    val = float(np.random.normal(loc=base_val, scale=std_adj))

                    is_rate_col = any(kw in col_name.lower() for kw in ["rate", "availability", "utilization", "_prb", "_cpu", "memory", "sr", "ratio", "compliance"])
                    if is_rate_col:
                        if min_val >= 90.0:
                            val = max(95.0, min(100.0, val))
                        else:
                            val = max(0.0, min(100.0, val))

                    elif "count" in col_name or "tickets" in col_name or "flaps" in col_name or "down" in col_name or "sites" in col_name:
                        val = max(0.0, val)

                    else:
                        val = max(min_val, val)


                is_count_col = any(kw in col_name.lower() for kw in ["count", "alarm", "sites", "cells", "down", "tickets", "users", "subs", "attempts", "incidents", "flaps"])
                if data_type in ("bigint", "integer", "smallint") or is_count_col:
                    row_data[col_name] = int(round(val))
                else:
                    row_data[col_name] = round(val, 4)


        # Post-processing ratio adjustments for Grafana calculated fields
        if "mc_push_to_talk_attempts" in row_data and row_data["mc_push_to_talk_attempts"]:
            attempts = float(row_data["mc_push_to_talk_attempts"])
            if attempts > 0:
                row_data["mc_push_to_talk_success"] = round(attempts * random.uniform(0.996, 0.998), 2)



        if "mc_video_attempts" in row_data and row_data["mc_video_attempts"]:
            v_attempts = float(row_data["mc_video_attempts"])
            if v_attempts > 0:
                row_data["mc_video_success"] = round(v_attempts * random.uniform(0.975, 0.990), 2)

        if "mc_data_attempts" in row_data and row_data["mc_data_attempts"]:
            d_attempts = float(row_data["mc_data_attempts"])
            if d_attempts > 0:
                row_data["mc_data_success"] = round(d_attempts * random.uniform(0.975, 0.990), 2)

        return row_data


    def generate_batch(self, table_name: str, count: int = 1, schema: str = "public", include_pk: bool = True):
        """Generates a batch of rows advancing timestamps sequentially."""
        rows = []
        schema_info = self.get_cached_schema(table_name, schema)
        date_cols = [c["column_name"] for c in schema_info if "timestamp" in c["data_type"].lower() or "date" in c["data_type"].lower()]
        
        latest_row = self.db.get_latest_record(table_name, schema)
        current_time = datetime.datetime.now()
        if self.advance_timestamp and latest_row and date_cols:
            d_col = date_cols[0]
            if latest_row.get(d_col):
                last_ts = latest_row[d_col]
                if isinstance(last_ts, str):
                    last_ts = datetime.datetime.fromisoformat(last_ts)
                current_time = last_ts

        current_base_row = latest_row

        for i in range(count):
            step_time = current_time + datetime.timedelta(seconds=self.timestamp_step_seconds * (i + 1))
            row = self.generate_row(table_name, schema, base_datetime=step_time, latest_row=current_base_row, include_pk=include_pk)
            rows.append(row)
            current_base_row = row

        return rows

if __name__ == "__main__":
    db = DBManager()
    gen = DataGenerator(db)
    sample_rows = gen.generate_batch("data_sample", count=2)
    print(f"Generated {len(sample_rows)} sample rows:")
    for r in sample_rows:
        print("  ID:", r.get("id"), "| Date:", r.get("date"), "| Latency:", r.get("latency"), "| VoLTE CSSR:", r.get("volte_cssr"), "| E2E Availability:", r.get("end_to_end_availability"))
    db.close_all()
