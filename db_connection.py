import logging
import os
import psycopg2
from psycopg2 import extras, pool
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DBConnection")

class DBManager:
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = self.load_config(config_path)
        self.db_cfg = self.config.get("database", {})
        self._pool = None
        self._init_pool()

    def load_config(self, config_path):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def _init_pool(self):
        try:
            self._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                host=self.db_cfg.get("host"),
                port=self.db_cfg.get("port", 5432),
                dbname=self.db_cfg.get("dbname"),
                user=self.db_cfg.get("user"),
                password=self.db_cfg.get("password"),
                sslmode=self.db_cfg.get("sslmode", "prefer"),
                connect_timeout=10
            )
            logger.info("PostgreSQL Connection Pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise

    def get_connection(self):
        if self._pool:
            return self._pool.getconn()
        return psycopg2.connect(
            host=self.db_cfg.get("host"),
            port=self.db_cfg.get("port", 5432),
            dbname=self.db_cfg.get("dbname"),
            user=self.db_cfg.get("user"),
            password=self.db_cfg.get("password"),
            sslmode=self.db_cfg.get("sslmode", "prefer"),
            connect_timeout=10
        )

    def release_connection(self, conn):
        if self._pool and conn:
            self._pool.putconn(conn)
        elif conn:
            conn.close()

    def close_all(self):
        if self._pool:
            self._pool.closeall()

    def test_connection(self):
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0]
                logger.info(f"Database connected successfully: {version}")
                return version
        finally:
            self.release_connection(conn)

    def sync_sequence(self, table_name, schema="public", id_column="id", conn=None):
        should_release = False
        if conn is None:
            conn = self.get_connection()
            should_release = True
        try:
            with conn.cursor() as cur:
                sql = f"""
                    SELECT setval(pg_get_serial_sequence('{schema}.{table_name}', '{id_column}'), COALESCE(MAX("{id_column}"), 1))
                    FROM "{schema}"."{table_name}";
                """
                cur.execute(sql)
                conn.commit()
                logger.info(f"Synced sequence for {schema}.{table_name}.{id_column}")
        except Exception as e:
            conn.rollback()
            logger.debug(f"Could not sync sequence for {table_name}: {e}")
        finally:
            if should_release:
                self.release_connection(conn)

    def get_table_schema(self, table_name, schema="public", conn=None):
        should_release = False
        if conn is None:
            conn = self.get_connection()
            should_release = True
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute("""
                    SELECT 
                        column_name, 
                        data_type, 
                        column_default, 
                        is_nullable, 
                        character_maximum_length,
                        ordinal_position
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position;
                """, (schema, table_name))
                columns = cur.fetchall()
                
                cur.execute("""
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = %s
                      AND tc.table_name = %s;
                """, (schema, table_name))
                pk_cols = set(r[0] for r in cur.fetchall())

                schema_info = []
                for col in columns:
                    col_dict = dict(col)
                    col_dict["is_primary_key"] = col["column_name"] in pk_cols
                    col_dict["is_auto_increment"] = (
                        col["column_default"] is not None and 
                        "nextval" in str(col["column_default"]).lower()
                    )
                    schema_info.append(col_dict)
                return schema_info
        finally:
            if should_release:
                self.release_connection(conn)

    def get_table_stats(self, table_name, schema="public", conn=None):
        should_release = False
        if conn is None:
            conn = self.get_connection()
            should_release = True

        schema_info = self.get_table_schema(table_name, schema, conn=conn)
        stats = {}
        
        numeric_cols = []
        text_cols = []
        date_cols = []

        for col in schema_info:
            col_name = col["column_name"]
            data_type = col["data_type"].lower()
            if col["is_auto_increment"] or (col["is_primary_key"] and "id" in col_name):
                continue
            if data_type in ("double precision", "real", "bigint", "integer", "numeric", "smallint"):
                numeric_cols.append(col_name)
            elif data_type in ("text", "character varying", "character"):
                text_cols.append(col_name)
            elif "timestamp" in data_type or "date" in data_type:
                date_cols.append(col_name)

        try:
            with conn.cursor() as cur:
                if numeric_cols:
                    select_exprs = []
                    for c in numeric_cols:
                        select_exprs.extend([
                            f'MIN("{c}")', f'MAX("{c}")', f'AVG("{c}")', f'STDDEV("{c}")'
                        ])
                    sql = f'SELECT {", ".join(select_exprs)} FROM "{schema}"."{table_name}";'
                    cur.execute(sql)
                    row = cur.fetchone()
                    
                    for idx, c in enumerate(numeric_cols):
                        base_idx = idx * 4
                        min_v = row[base_idx]
                        max_v = row[base_idx + 1]
                        avg_v = row[base_idx + 2]
                        std_v = row[base_idx + 3]
                        stats[c] = {
                            "type": "numeric",
                            "min": float(min_v) if min_v is not None else 0.0,
                            "max": float(max_v) if max_v is not None else 100.0,
                            "avg": float(avg_v) if avg_v is not None else 50.0,
                            "stddev": float(std_v) if std_v is not None and std_v > 0 else 1.0
                        }

                if date_cols:
                    select_exprs = []
                    for c in date_cols:
                        select_exprs.extend([f'MIN("{c}")', f'MAX("{c}")'])
                    sql = f'SELECT {", ".join(select_exprs)} FROM "{schema}"."{table_name}";'
                    cur.execute(sql)
                    row = cur.fetchone()
                    for idx, c in enumerate(date_cols):
                        base_idx = idx * 2
                        stats[c] = {
                            "type": "datetime",
                            "min": row[base_idx],
                            "max": row[base_idx + 1]
                        }

                for c in text_cols:
                    cur.execute(f'SELECT DISTINCT "{c}" FROM "{schema}"."{table_name}" WHERE "{c}" IS NOT NULL LIMIT 20;')
                    distincts = [r[0] for r in cur.fetchall() if r[0] is not None]
                    stats[c] = {
                        "type": "categorical",
                        "choices": distincts if distincts else ["Active"]
                    }

            return stats
        finally:
            if should_release:
                self.release_connection(conn)

    def get_latest_record(self, table_name, schema="public", conn=None):
        should_release = False
        if conn is None:
            conn = self.get_connection()
            should_release = True

        schema_info = self.get_table_schema(table_name, schema, conn=conn)
        date_cols = [c["column_name"] for c in schema_info if "timestamp" in c["data_type"].lower() or "date" in c["data_type"].lower()]
        pk_cols = [c["column_name"] for c in schema_info if c["is_primary_key"]]

        order_col = date_cols[0] if date_cols else (pk_cols[0] if pk_cols else schema_info[0]["column_name"])

        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f'SELECT * FROM "{schema}"."{table_name}" ORDER BY "{order_col}" DESC LIMIT 1;')
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.debug(f"Error fetching latest record from {table_name}: {e}")
            return None
        finally:
            if should_release:
                self.release_connection(conn)

if __name__ == "__main__":
    db = DBManager()
    db.test_connection()
    db.sync_sequence("data_sample")
    cols = db.get_table_schema("data_sample")
    print(f"data_sample has {len(cols)} columns.")
    db.close_all()
