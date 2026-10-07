"""End-to-end: a real browser clicks through the portal (desktop and phone sizes)."""
import threading

import pytest
from werkzeug.serving import make_server

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def base_url():
    import app as portal
    srv = make_server("127.0.0.1", 0, portal.app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge")
        except Exception:
            b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    # blocked steps answer 409/400 on purpose; the browser logs those as "Failed to load resource"
    pg.on("console", lambda m: m.type == "error" and "fonts.g" not in m.text and "Failed to load resource" not in m.text
          and pg.errors.append(m.text))
    pg.on("dialog", lambda d: d.accept())
    yield pg
    ctx.close()


def toast_after(page, action):
    """Run the action and return the text of the notification it produces."""
    page.evaluate("document.getElementById('toast').innerHTML = ''")
    action()
    page.wait_for_selector("#toast div", timeout=120_000)
    return page.locator("#toast div").last.inner_text()


VIEWS = ["dashboard", "purchases", "purchase-edit/new", "advances", "advance-edit/new", "reimbursements",
         "reimbursement-edit/new", "vendors", "items", "settings"]


@pytest.mark.parametrize("width", [1366, 390])
def test_every_page_loads_cleanly(browser, base_url, width):
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    for v in VIEWS:
        pg.goto(f"{base_url}/#{v}")
        pg.wait_for_selector("main h1")
        overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"{v} scrolls sideways by {overflow}px at {width}px"
    assert not errors
    ctx.close()


def fill_quote(card, vendor, desc, qty, rate):
    v = card.locator('[data-t="vendor"]')
    v.fill(vendor)
    v.dispatch_event("change")
    card.locator('[data-t="item-desc"]').first.fill(desc)
    card.locator('[data-t="item-qty"]').first.fill(str(qty))
    card.locator('[data-t="item-rate"]').first.fill(str(rate))


def test_purchase_end_to_end(page, base_url):
    page.goto(f"{base_url}/#purchase-edit/new")
    page.fill('[data-t="title"]', "Motor drivers for UI test")
    cards = page.locator('[data-t="quote"]')
    fill_quote(cards.nth(0), "ALL TECH ELECTRONICS", "Sabertooth Dual 32A", 2, 11450)
    assert page.locator("input[placeholder='15-character GSTIN']").first.input_value() == "24ACVPG3865E1ZF"
    assert cards.nth(0).locator('[data-t="quote-total"]').inner_text() == "₹27,022.00"
    page.wait_for_function("document.querySelector('[data-t=amount]').textContent.includes('27,022.00')")
    assert "Director" in page.locator('[data-t="route"]').inner_text()

    # not enough quotations yet
    assert "needs 3 quotations" in toast_after(page, lambda: page.click('[data-t="gen-permission"]'))

    for name, rate in (("PRAYOGTECH", 12584.75), ("MACFOS LIMITED", 12007.63)):
        page.click('[data-t="add-quote"]')
        fill_quote(cards.last, name, "Sabertooth Dual 32A", 2, rate)
    page.wait_for_function("document.querySelector('[data-t=slip]').textContent.includes('3 of 3')")

    # choosing a costlier vendor warns about L1
    cards.nth(1).locator('[data-t="select-quote"]').check()
    page.wait_for_selector('[data-t="l1-note"]')
    cards.nth(0).locator('[data-t="select-quote"]').check()
    page.wait_for_selector('[data-t="l1-note"]', state="detached")

    page.click('[data-t="gen-permission"]')
    page.wait_for_selector('[data-t="doc-permission"]', timeout=120_000)
    assert "#purchase-edit/" in page.url and page.url[-1].isdigit()

    assert "not approved" in toast_after(page, lambda: page.click('[data-t="gen-po"]'))
    page.check('[data-t="stage-permission_approved"]')
    page.wait_for_selector('label.step.done >> text=Permission approved')
    page.click('[data-t="gen-po"]')
    page.wait_for_selector('[data-t="doc-po"]', timeout=120_000)

    # locked step cannot be ticked out of order
    assert "Pending first" in toast_after(page, lambda: page.check('[data-t="stage-outward"]'))
    assert not page.is_checked('[data-t="stage-outward"]')

    # the PDF link opens a real PDF
    href = page.evaluate("""() => { const a=[...document.querySelectorAll('[data-t=doc-po] .links a')].find(x=>x.textContent==='PDF'); return a.title; }""")
    assert href.endswith(".pdf")
    assert not page.errors

    # it is listed on the overview
    page.click('nav a[data-view="dashboard"]')
    page.wait_for_selector('[data-t="purchase-table"] >> text=Motor drivers for UI test')


def test_round_off_button(page, base_url):
    page.goto(f"{base_url}/#purchase-edit/new")
    card = page.locator('[data-t="quote"]').first
    fill_quote(card, "Some Vendor", "Odd priced part", 3, 999.99)
    card.locator("details.more > summary").click()
    card.locator('[data-t="round"]').click()
    assert page.locator('[data-t="quote"]').first.locator('[data-t="quote-total"]').inner_text() == "₹3,540.00"


def test_vendor_add_and_search(page, base_url):
    page.goto(f"{base_url}/#vendors")
    page.click('[data-t="add-vendor"]')
    assert "name" in toast_after(page, lambda: page.click('[data-t="vendor-save"]'))
    page.fill('[data-t="vendor-name"]', "UI TEST TRADERS")
    page.click('[data-t="vendor-save"]')
    page.fill('[data-t="vendor-search"]', "ui test")
    page.wait_for_selector("text=UI TEST TRADERS")


def test_advance_and_ledger(page, base_url):
    page.goto(f"{base_url}/#advance-edit/new")
    page.fill('[data-t="adv-title"]', "UI advance")
    page.fill('[data-t="adv-item"]', "Bolts")
    page.fill('[data-t="adv-rate"]', "500")
    assert page.input_value('[data-t="adv-amount"]') == "500"
    assert "Advance amount received" in toast_after(page, lambda: page.click('[data-t="gen-adj"]'))
    page.click('[data-t="gen-adv"]')
    page.wait_for_selector('[data-t="doc-advance_voucher"]', timeout=120_000)
    assert "Pending first" in toast_after(page, lambda: page.check('[data-t="stage-issued"]'))

    page.goto(f"{base_url}/#settings")
    page.fill('[data-t="ledger-note"]', "UI overhead")
    page.fill('[data-t="ledger-amount"]', "1234")
    page.click('[data-t="ledger-add"]')
    page.wait_for_selector('[data-t="ledger"] >> text=UI overhead')
    assert not page.errors
