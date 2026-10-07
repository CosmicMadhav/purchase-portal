"""Every test run uses its own throw-away database and output folder – never the real data/."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="portal-test-")
os.environ["PORTAL_DB"] = os.path.join(TMP, "test.db")
os.environ["OUTPUT_DIR"] = os.path.join(TMP, "output")
os.environ.pop("APP_PASSWORD", None)

import pytest  # noqa: E402

import store  # noqa: E402

store.init()


@pytest.fixture(scope="session")
def tmpdir_root():
    return TMP


@pytest.fixture()
def app_client():
    import app as portal
    portal.app.config["TESTING"] = True
    with portal.app.test_client() as c:
        yield c


@pytest.fixture(scope="session")
def profile():
    return store.all_("projects", "id ASC")[0]


def quote(vendor, items, **kw):
    q = {"vendor": {"name": vendor, "address": "Line 1\nLine 2", "gst": "24AAAAA0000A1Z5"},
         "payment": "After 15 days", "delivery": "7-10 days",
         "items": [{"description": d, "qty": q_, "rate": r, "gst": 18} for d, q_, r in items]}
    q.update(kw)
    return q
