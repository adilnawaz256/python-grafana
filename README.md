# PostgreSQL Telemetry Data Generator & Cron Scheduler

This Python application connects to your AWS RDS PostgreSQL database, introspects the database schema and statistical distributions, dynamically generates realistic NOC telemetry / KPI data matching the DB schema without requiring schema changes, and continuously pushes the data on a configurable schedule.

---

## 📌 Database Connection Details
- **Host**: `database-1.c90s8acs6gvg.eu-west-2.rds.amazonaws.com`
- **Port**: `5432`
- **Database**: `postgres`
- **User**: `postgres`
- **Password**: `StrongPassword123!`

---

## 📁 Repository Structure

| File | Description |
| :--- | :--- |
| `config.yaml` | Connection credentials, cron schedules, target tables, and noise settings. |
| `db_connection.py` | PostgreSQL connection pool manager, schema introspection, & stats profiler. |
| `data_generator.py` | Dynamic schema-aware synthetic telemetry data generator. |
| `db_pusher.py` | Transactional batch PostgreSQL data inserter using `execute_values`. |
| `scheduler.py` | APScheduler background daemon supporting interval & standard cron expressions. |
| `main.py` | CLI entrypoint with `inspect`, `generate-once`, and `start-daemon` commands. |
| `requirements.txt` | Python package dependencies (`psycopg2-binary`, `PyYAML`, `APScheduler`, `Faker`). |

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
python3 -m pip install -r requirements.txt
```

### 2. Inspect Database Schema & Current Statistics
To test the DB connection and inspect table row counts, column types, and latest record dates:
```bash
python3 main.py inspect
```

### 3. Generate a Single Batch of Data (Manual / On-Demand)
To generate and immediately insert 5 new records into `data_sample`:
```bash
python3 main.py generate-once --count 5 --table data_sample
```

### 4. Start Continuous Scheduled Cron Generator Daemon
To start the daemon that continuously generates and inserts new telemetry data based on `config.yaml`:
```bash
python3 main.py start-daemon
```

---

## ⚙️ Configuration (`config.yaml`)

```yaml
# PostgreSQL Database Credentials
database:
  host: "database-1.c90s8acs6gvg.eu-west-2.rds.amazonaws.com"
  port: 5432
  dbname: "postgres"
  user: "postgres"
  password: "StrongPassword123!"
  sslmode: "prefer"
  schema: "public"

# Cron Schedule & Generator Settings
scheduler:
  # Mode: "interval" (every N seconds) or "cron" (5-field expression)
  mode: "interval"
  interval_seconds: 60
  cron_expression: "*/1 * * * *"
  batch_size: 1

target_tables:
  - "data_sample"

generator_settings:
  advance_timestamp_from_latest: true
  timestamp_step_seconds: 60
  noise_factor: 0.05
```

---

## 🕒 OS Crontab Integration (Alternative)

If you prefer to run single batch generations via standard OS `crontab` instead of the background daemon:

1. Open your crontab editor:
   ```bash
   crontab -e
   ```
2. Add a line to run `main.py generate-once` every 5 minutes:
   ```cron
   */5 * * * * /usr/bin/python3 /Users/adilnawaz/Music/PythonGrafana/main.py generate-once --count 1 >> /Users/adilnawaz/Music/PythonGrafana/cron.log 2>&1
   ```
