import oracledb
import os
from dotenv import load_dotenv

# This line is CRITICAL. It looks for the .env file and loads it.
load_dotenv() 

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_DSN = os.getenv("DB_DSN")

def get_connection():
    # Adding a print here will help us debug if the variables are empty
    if not DB_USER or not DB_PASSWORD:
        print("ERROR: Database credentials not found in environment!")
    
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)
def init_db():
    conn = get_connection()
    cur  = conn.cursor()

    tables = [
        # USERS
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_users (
                id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username      VARCHAR2(100) UNIQUE NOT NULL,
                password_hash VARCHAR2(200) NOT NULL,
                created_at    DATE DEFAULT SYSDATE
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # CATEGORIES
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_categories (
                id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name       VARCHAR2(100) NOT NULL,
                is_default CHAR(1) DEFAULT ''N'',
                user_id    NUMBER
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # HABITS (daily and monthly)
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_habits (
                id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id      NUMBER NOT NULL,
                name         VARCHAR2(200) NOT NULL,
                category_id  NUMBER,
                habit_type   VARCHAR2(10) DEFAULT ''daily'',
                start_time   VARCHAR2(10),
                end_time     VARCHAR2(10),
                start_date   DATE DEFAULT SYSDATE,
                end_date     DATE,
                status       VARCHAR2(20) DEFAULT ''active'',
                created_at   DATE DEFAULT SYSDATE
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # SUB HABITS
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_sub_habits (
                id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                habit_id   NUMBER NOT NULL,
                name       VARCHAR2(200) NOT NULL
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # DAILY LOGS (one row per habit per day)
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_habit_logs (
                id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                habit_id   NUMBER NOT NULL,
                log_date   DATE DEFAULT SYSDATE,
                is_done    CHAR(1) DEFAULT ''N''
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # SUB HABIT LOGS
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_sub_logs (
                id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                sub_habit_id NUMBER NOT NULL,
                log_date     DATE DEFAULT SYSDATE,
                is_done      CHAR(1) DEFAULT ''N''
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # STREAKS
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_streaks (
                id             NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                habit_id       NUMBER UNIQUE NOT NULL,
                current_streak NUMBER DEFAULT 0,
                longest_streak NUMBER DEFAULT 0,
                total_points   NUMBER DEFAULT 0
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",

        # DELETED STREAKS ARCHIVE
        """BEGIN EXECUTE IMMEDIATE '
            CREATE TABLE hf_deleted_streaks (
                id             NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id        NUMBER NOT NULL,
                habit_name     VARCHAR2(200),
                streak_count   NUMBER DEFAULT 0,
                start_date     DATE,
                end_date       DATE,
                category_name  VARCHAR2(100),
                deleted_at     DATE DEFAULT SYSDATE
            )
        '; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;""",
    ]

    for sql in tables:
        cur.execute(sql)

    # Default categories
    defaults = ["Health", "Study", "Fitness", "Personal", "Work", "Others"]
    for name in defaults:
        cur.execute(
            "SELECT COUNT(*) FROM hf_categories WHERE name=:1 AND is_default='Y'",
            [name]
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO hf_categories (name, is_default) VALUES (:1, 'Y')",
                [name]
            )

    conn.commit()
    cur.close()
    conn.close()
    print("HabitFlow DB initialised.")