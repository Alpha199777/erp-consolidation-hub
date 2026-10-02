import pytest
from dotenv import load_dotenv

from hub.load import connect, sync_source, upsert_customers
from hub.models import Customer

load_dotenv()

SOURCE = "pytest"


@pytest.fixture
def conn():
    try:
        c = connect()
    except Exception as exc:  # base indisponible ou variable absente
        pytest.skip(f"Base du hub indisponible : {exc}")
    clean = ("DELETE FROM raw.customers WHERE source = %s",
             "DELETE FROM raw.sync_runs WHERE source = %s")
    for sql in clean:
        c.execute(sql, (SOURCE,))
    yield c
    for sql in clean:
        c.execute(sql, (SOURCE,))
    c.close()


def customer(i, **kw):
    values = dict(source=SOURCE, source_id=str(i), name=f"Client {i}", email=None,
                  phone=None, city=None, postal_code=None, country=None,
                  payload={"id": i})
    values.update(kw)
    return Customer(**values)


class FakeConnector:
    source = SOURCE

    def __init__(self, ids, fail=False):
        self.ids = ids
        self.fail = fail

    def fetch_customers(self):
        if self.fail:
            raise RuntimeError("boom")
        return [{"id": i} for i in self.ids]

    def normalize(self, record):
        return customer(record["id"])


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM raw.{table} WHERE source = %s",
                        (SOURCE,)).fetchone()[0]


# --- upsert -------------------------------------------------------------

def test_upsert_inserts_rows(conn):
    assert upsert_customers(conn, [customer(1), customer(2), customer(3)]) == 3
    assert count(conn, "customers") == 3


def test_upsert_twice_creates_no_duplicates(conn):
    batch = [customer(1), customer(2), customer(3)]
    upsert_customers(conn, batch)
    upsert_customers(conn, batch)
    assert count(conn, "customers") == 3


def test_upsert_updates_values_and_keeps_first_seen_at(conn):
    upsert_customers(conn, [customer(1, name="Ancien nom")])
    first = conn.execute(
        "SELECT first_seen_at FROM raw.customers WHERE source = %s", (SOURCE,)
    ).fetchone()[0]

    upsert_customers(conn, [customer(1, name="Nouveau nom")])
    name, first_after, last = conn.execute(
        "SELECT name, first_seen_at, last_synced_at FROM raw.customers "
        "WHERE source = %s", (SOURCE,)
    ).fetchone()
    assert name == "Nouveau nom"
    assert first_after == first
    assert last > first


def test_upsert_empty_list_returns_zero(conn):
    assert upsert_customers(conn, []) == 0


def test_payload_is_stored_as_json(conn):
    payload = {"id": 7, "tags": ["a", "b"], "vide": None}
    upsert_customers(conn, [customer(7, payload=payload)])
    stored = conn.execute(
        "SELECT payload FROM raw.customers WHERE source = %s", (SOURCE,)
    ).fetchone()[0]
    assert stored == payload


# --- sync_source + journal ----------------------------------------------

def test_sync_success_is_recorded_in_journal(conn):
    result = sync_source(conn, FakeConnector([1, 2, 3]))
    assert (result.status, result.rows_fetched, result.rows_loaded) == ("success", 3, 3)

    status, fetched, loaded, finished, error = conn.execute(
        "SELECT status, rows_fetched, rows_loaded, finished_at, error_message "
        "FROM raw.sync_runs WHERE run_id = %s", (result.run_id,)
    ).fetchone()
    assert (status, fetched, loaded, error) == ("success", 3, 3, None)
    assert finished is not None


def test_two_syncs_keep_customer_count_and_add_journal_lines(conn):
    sync_source(conn, FakeConnector([1, 2, 3]))
    sync_source(conn, FakeConnector([1, 2, 3]))
    assert count(conn, "customers") == 3
    assert count(conn, "sync_runs") == 2


def test_sync_failure_is_recorded_and_not_raised(conn):
    result = sync_source(conn, FakeConnector([1], fail=True))
    assert result.status == "failed"
    assert "boom" in result.error

    status, error = conn.execute(
        "SELECT status, error_message FROM raw.sync_runs WHERE run_id = %s",
        (result.run_id,),
    ).fetchone()
    assert status == "failed"
    assert "boom" in error
    assert count(conn, "customers") == 0