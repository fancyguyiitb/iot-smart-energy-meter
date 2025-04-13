from sprint import Logger
import sqlite3

DB_NAME = "power_meter_data.db"

l = Logger.get_instance(debug=True)


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS power_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phase TEXT,
            voltage_rms REAL,
            current_rms REAL,
            active_power REAL,
            reactive_power REAL,
            apparent_power REAL,
            energy_kwh REAL,
            voltage_thd REAL,
            current_thd REAL,
            power_factor REAL,
            voltage_freq REAL,
            timestamp TEXT,
            sync BOOLEAN DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def insert_power_data(
    phase,
    voltage_rms,
    current_rms,
    active_power,
    reactive_power,
    apparent_power,
    voltage_thd,
    current_thd,
    power_factor,
    voltage_freq,
    timestamp,
    energy_kwh=None,
    sync=False,
):
    if energy_kwh is None:
        energy_kwh = 0.0

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        # Insert the new row
        cursor.execute(
            """
            INSERT INTO power_data (
                phase, voltage_rms, current_rms, active_power,
                reactive_power, apparent_power, energy_kwh,
                voltage_thd, current_thd, power_factor, voltage_freq, timestamp, sync
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                phase,
                voltage_rms,
                current_rms,
                active_power,
                reactive_power,
                apparent_power,
                energy_kwh,
                voltage_thd,
                current_thd,
                power_factor,
                voltage_freq,
                timestamp,
                sync,
            ),
        )

        # Enforce maximum row limit
        cursor.execute("SELECT COUNT(*) FROM power_data")
        total_rows = cursor.fetchone()[0]

        MAX_ROWS = 1000000
        if total_rows > MAX_ROWS:
            rows_to_delete = total_rows - MAX_ROWS
            l.iprint(f"Deleting {rows_to_delete} oldest entries to maintain row limit")
            cursor.execute(
                """
                DELETE FROM power_data
                WHERE id IN (
                    SELECT id FROM power_data
                    ORDER BY id ASC
                    LIMIT ?
                )
                """,
                (rows_to_delete,),
            )

        conn.commit()

    except Exception as e:
        l.eprint("Error in insert_power_data:", e)
        conn.rollback()

    finally:
        conn.close()


def get_unsynced_data() -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM power_data WHERE sync = 0")
    data = cursor.fetchall()

    conn.close()

    formatted_data = []
    for row in data:
        formatted_data.append(
            {
                "id": row[0],
                "phase": row[1],
                "voltage_rms": row[2],
                "current_rms": row[3],
                "power_watt": row[4] or 0.0,
                "power_var": row[5] or 0.0,
                "power_va": row[6] or 0.0,
                "energy_kwh": row[7] or 0.0,
                "voltage_thd": row[8] or 0.0,
                "current_thd": row[9] or 0.0,
                "power_factor": row[10] or 0.0,
                "voltage_freq": row[11] or 0.0,
                "time": row[12] + "Z",
            }
        )
    if formatted_data:
        l.iprint("Sample Formatted Data: ", formatted_data[0])

    return formatted_data


def get_last_max_energy(phase):
    """Fetches the last stored maximum energy value from the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT MAX(energy_kwh) FROM power_data WHERE phase = ?", (phase,)
        )  # FIXME: Instead of using max use last val.
        last_max_energy = cursor.fetchone()[0]
    except Exception as e:
        l.eprint("Error fetching last max energy:", e)
        return 0.0
    finally:
        cursor.close()
        conn.close()

    return last_max_energy


def update_row_sync_status(row_ids):
    """Updates the sync status of the rows with the given IDs to True within a transaction."""
    if not row_ids:
        return 0  # No rows to update

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        l.iprint("Updating sync status of rows with IDs:", row_ids)
        cursor.execute("BEGIN TRANSACTION;")
        cursor.execute(
            "UPDATE power_data SET sync = 1 WHERE id IN ({})".format(
                ",".join("?" * len(row_ids))
            ),
            tuple(row_ids),
        )

        row_count = cursor.rowcount
        conn.commit()
        l.iprint("Updated: ", row_count, "rows")
    except Exception as e:
        conn.rollback()
        l.eprint("Error updating sync status:", e)
        raise e  # Re-raise the exception after rollback
    finally:
        cursor.close()
        conn.close()

    return row_count
