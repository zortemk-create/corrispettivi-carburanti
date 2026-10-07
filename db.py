import os
import psycopg2
import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(BASE_DIR, '.env')


def _load_env():
    env = {}
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


ENV = {**_load_env(), **os.environ}

DB_CONFIG = {
    'host': ENV.get('DB_HOST', 'localhost'),
    'port': ENV.get('DB_PORT', '5432'),
    'dbname': ENV.get('DB_NAME', 'tagesabrechnung'),
    'user': ENV.get('DB_USER', 'postgres'),
    'password': ENV.get('DB_PASSWORD', ''),
}


def get_connection():
    return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **DB_CONFIG)


def init_schema():
    """Legt das eigene Schema 'corrispettivi' an. Die Tabellen der Tagesabrechnung werden nur gelesen."""
    with open(os.path.join(BASE_DIR, 'schema.sql'), 'r', encoding='utf-8') as f:
        sql = f.read()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()
