import os
import json
import platform
from flask import session, has_request_context
from .config import BASE_DIR

class _ProdCursorWrapper:
    """Wraps a pyodbc cursor to expose dict-like rows (matching sqlite3.Row)."""

    def __init__(self, cursor):
        self._cur = cursor

    def _to_dict(self, row):
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))

    def fetchall(self):
        return [self._to_dict(r) for r in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        return self._to_dict(row) if row is not None else None

    def __getattr__(self, name):
        return getattr(self._cur, name)


class DbConnection:
    """pyodbc connection wrapper for LOCAL and PROD SQL Server.

    Both environments use pyodbc; rows are returned as dicts via _ProdCursorWrapper.
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return _ProdCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    # context-manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _PymssqlDbConnection(DbConnection):
    """pymssql-backed connection wrapper.

    pymssql uses %s placeholders; this subclass converts ? → %s transparently
    so all caller code stays identical to the pyodbc path.
    """

    def execute(self, sql: str, params=()):
        sql_converted = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql_converted, params if params else ())
        return _ProdCursorWrapper(cur)


def get_db() -> DbConnection:
    """Return the local SQL Server connection (Deals, CustomerDetail, cached Customer)."""
    return _get_db_local()


def get_customer_db() -> DbConnection:
    """Return connection to SRVDNZ BOA database if PROD, else local SQL Server."""
    env = session.get("env", "local") if has_request_context() else "local"
    if env == "prod":
        return _get_db_prod()
    return _get_db_local()


def _get_db_local() -> DbConnection:
    """LOCAL connection — autocommit=False."""
    return _make_local_conn(autocommit=False)


def _get_db_prod() -> DbConnection:
    """PROD connection with autocommit=False (for regular reads/writes)."""
    return _make_prod_conn(autocommit=False)


def _get_db_prod_autocommit() -> DbConnection:
    """PROD connection with autocommit=True (required for multi-statement batches with temp tables)."""
    return _make_prod_conn(autocommit=True)


def _make_local_conn(autocommit: bool = False) -> DbConnection:
    """OS-aware factory: connection to the local SQL Server instance.

    - macOS / Linux  → Docker container, pymssql + SQL Auth (sa + config.json)
                       No system ODBC library required — pymssql bundles FreeTDS.
    - Windows        → Installed SQL Server Express/Developer, pyodbc + Windows Auth
    """
    config_path = os.path.join(BASE_DIR, "config.json")
    config: dict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as exc:
            print(f"Warning: Failed to load config.json: {exc}")

    db_name = config.get("LOCAL_DB_NAME", "BOA")
    os_name = platform.system()

    if os_name == "Windows":
        # Windows: pyodbc + Windows Auth (ODBC built into every Windows install)
        try:
            import pyodbc  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("pyodbc is not installed. Run: pip install pyodbc") from exc

        server = config.get("LOCAL_WIN_SERVER", r".\SQLEXPRESS")
        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
        if not drivers:
            raise RuntimeError(
                "No SQL Server ODBC driver found. "
                "Install 'ODBC Driver 17/18 for SQL Server' from Microsoft."
            )
        driver = next((d for d in drivers if "18" in d), None) or drivers[0]
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={db_name};"
            "Trusted_Connection=yes;"
        )
        try:
            raw = pyodbc.connect(conn_str, autocommit=autocommit, timeout=10)
            return DbConnection(raw)
        except Exception as exc:
            raise RuntimeError(f"LOCAL connection failed ({server}/{db_name}): {exc}") from exc

    else:
        # macOS / Linux: pymssql — no system ODBC library required
        try:
            import pymssql  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("pymssql is not installed. Run: pip3 install pymssql") from exc

        server_full = config.get("LOCAL_SERVER", "localhost,1433")
        server_addr = server_full.replace(",", ":")  # pymssql uses 'host:port'
        sa_user = config.get("LOCAL_SA_USER", "sa")
        sa_pass = config.get("LOCAL_SA_PASSWORD", "")
        try:
            raw = pymssql.connect(
                server=server_addr,
                user=sa_user,
                password=sa_pass,
                database=db_name,
                login_timeout=10,
            )
            if autocommit:
                raw.autocommit(True)
            return _PymssqlDbConnection(raw)
        except Exception as exc:
            raise RuntimeError(f"LOCAL connection failed ({server_full}/{db_name}): {exc}") from exc


def _make_prod_conn(autocommit: bool = False) -> DbConnection:
    """Internal factory: build a pyodbc connection to SRVDNZ/BOA."""
    try:
        import pyodbc  # noqa: PLC0415 — optional dependency
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc is not installed. Run: pip install pyodbc"
        ) from exc

    server  = "SRVDNZ"
    db_name = ""
    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                server = config.get("PROD_SERVER", server)
                db_name = config.get("PROD_DB_NAME", db_name)
        except Exception as exc:
            print(f"Warning: Failed to load config.json: {exc}")

    # Auto-detect installed SQL Server ODBC driver (prefer 18, then 17)
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if not drivers:
        raise RuntimeError(
            "No SQL Server ODBC driver found. "
            "Install 'ODBC Driver 17 for SQL Server' or '18 for SQL Server'."
        )
    driver = next((d for d in drivers if "18" in d), None) or drivers[0]

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        + (f"DATABASE={db_name};" if db_name else "")
        + "Trusted_Connection=yes;"
    )
    try:
        raw = pyodbc.connect(conn_str, autocommit=autocommit, timeout=10)
        return DbConnection(raw)
    except Exception as exc:
        raise RuntimeError(f"PROD connection failed ({server}/{db_name}): {exc}") from exc
