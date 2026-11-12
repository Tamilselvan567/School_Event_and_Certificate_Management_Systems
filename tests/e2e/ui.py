"""Small helpers for driving the Streamlit screens."""
import re

STAFF_TAB = "Teacher / Admin Login"
BAD = ["Something went wrong", "Traceback", "StreamlitAPIException", "AttributeError", "KeyError", "TypeError"]


def open_app(page, live, query=""):
    page.goto(live.url + query, wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="stApp"]')
    wait_idle(page)


def wait_idle(page, ms=350):
    """Wait until Streamlit has finished running the script."""
    page.wait_for_timeout(ms)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]') && "
        "document.querySelectorAll('[data-testid=\"stSkeleton\"]').length === 0", timeout=30000)
    page.wait_for_timeout(150)


def assert_clean(page):
    assert page.locator('[data-testid="stException"]').count() == 0, "Streamlit exception shown on page"
    body = page.inner_text("body")
    for bad in BAD:
        assert bad not in body, f"page shows '{bad}'"


def choose(page, label, option):
    """Pick an entry in a Streamlit dropdown (retries, because a click during a re-run can be swallowed)."""
    box = page.get_by_label(label, exact=True).filter(visible=True).first
    opt = page.get_by_role("option", name=option, exact=True).first
    for _ in range(4):
        wait_idle(page, 200)
        box.click()
        try:
            opt.wait_for(state="visible", timeout=2500)
            break
        except Exception:
            page.keyboard.press("Escape")
    opt.click()
    wait_idle(page)


def click_button(page, name, exact=True):
    page.get_by_role("button", name=name, exact=exact).first.click()
    wait_idle(page)


def login_staff(page, live, username, password):
    open_app(page, live)
    page.get_by_role("tab", name=STAFF_TAB).click()
    page.get_by_label("Username", exact=True).fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.keyboard.press("Tab")
    click_button(page, "Log in")


def login_student(page, live, name, cls, section, roll):
    open_app(page, live)
    choose(page, "Class", cls)
    choose(page, "Section", section)
    page.get_by_label("Your full name").fill(name)
    page.get_by_label("Roll number").fill(roll)
    page.keyboard.press("Tab")
    click_button(page, "Enter my dashboard")


def nav(page, label):
    page.locator('[data-testid="stSidebar"]').get_by_text(label, exact=True).click()
    wait_idle(page, 600)


def logout(page):
    click_button(page, "🚪 Log out")


def field(page, label):
    """The visible text box / text area with this label (Streamlit keeps hidden tabs in the page)."""
    return page.locator(f'input[aria-label="{label}"]:visible, textarea[aria-label="{label}"]:visible').first


def see(page, text, timeout=25000):
    """Wait until some element showing this text is visible, and return it."""
    loc = page.get_by_text(text).filter(visible=True).first
    loc.wait_for(state="visible", timeout=timeout)
    return loc


def choose_contains(page, label, text):
    """Pick the dropdown entry whose text CONTAINS `text`."""
    box = page.get_by_label(label, exact=True).filter(visible=True).first
    opt = page.get_by_role("option").filter(has_text=text).first
    for _ in range(4):
        wait_idle(page, 200)
        box.click()
        try:
            opt.wait_for(state="visible", timeout=2500)
            break
        except Exception:
            page.keyboard.press("Escape")
    opt.click()
    wait_idle(page, 500)
