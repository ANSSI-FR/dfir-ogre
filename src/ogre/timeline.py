from chdb import session


def build_timeline(input_data_path: str, timeline_file: str, database_path: str):
    sess = session.Session(database_path)
    sess.query("""CREATE DATABASE IF NOT EXISTS analytics ENGINE = Atomic""")
    sess.query("USE analytics")
    sess.query("""
        CREATE OR REPLACE TABLE timeline
        (
            timestamp String,
            timestamp_meaning String,
            data_type String,
            related_user String,
            description String,
            additional_description String,
        ) 
        ENGINE = MergeTree
        ORDER BY timestamp
    """)

    sess.query(f"""
        INSERT INTO timeline
        SELECT
            timestamp, timestamp_meaning, data_type, related_user,
            description, additional_description
        FROM file('{input_data_path}/*.*.jsonl', JSONEachRow)
    """)

    sess.query(f"""
        SELECT
            timestamp, timestamp_meaning, data_type, related_user,
            description, additional_description
        FROM timeline
        ORDER BY timestamp
        INTO OUTFILE  '{timeline_file}' TRUNCATE FORMAT CSVWithNames
    """)

    sess.query("DROP TABLE timeline")

    sess.close()
