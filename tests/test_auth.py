"""Logging in and out, the owner command, the login cookie, CSRF and the demo."""
from sqlalchemy import select

from stickyminutes import db, seed
from stickyminutes.dates import plus, utcnow
from stickyminutes.models import User, Workspace

from .conftest import PASSWORD, browser, is_logged_in, make_owner, post, text, words


def test_the_start_page_sends_visitors_to_the_login(client):
    response = client.get("/")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")


def test_the_owner_logs_in_and_out(app, client):
    make_owner(app)
    response = post(client, "/login", {"email": "MARIA@example.com ", "password": PASSWORD})
    assert response.status_code == 302 and response.headers["Location"].endswith("/meetings")
    assert is_logged_in(client)
    response = post(client, "/logout")
    assert response.status_code == 302
    assert not is_logged_in(client)


def test_a_wrong_password_says_the_same_as_a_missing_account(app, client):
    make_owner(app)
    wrong = post(client, "/login", {"email": "maria@example.com", "password": "nope"})
    missing = post(client, "/login", {"email": "nobody@example.com", "password": "nope"})
    assert wrong.status_code == missing.status_code == 401
    assert "Wrong email or password." in text(wrong) and "Wrong email or password." in text(missing)


def test_five_wrong_passwords_lock_the_account(app, client):
    make_owner(app)
    for _ in range(5):
        post(client, "/login", {"email": "maria@example.com", "password": "nope"})
    response = post(client, "/login", {"email": "maria@example.com", "password": PASSWORD})
    assert "wait 15 minutes" in text(response)


def test_pages_need_a_login(client):
    response = client.get("/meetings")
    assert response.status_code == 302 and "/login?next=/meetings" in response.headers["Location"]


def test_a_form_without_the_csrf_token_is_refused(app, client):
    make_owner(app)
    response = client.post("/login", data={"email": "maria@example.com", "password": PASSWORD})
    assert response.status_code == 400 and "expired" in text(response)


def test_after_login_only_pages_on_this_site(app, client):
    make_owner(app)
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        response = post(client, "/login", {"email": "maria@example.com", "password": PASSWORD, "next": bad})
        assert response.headers["Location"].endswith("/meetings"), bad
        post(client, "/logout")


def test_the_login_cookie_has_its_own_name(app, client):
    """Every Flask app calls its cookie "session", and 127.0.0.1 shares cookies across ports."""
    assert app.config["SESSION_COOKIE_NAME"] == "stickyminutes_session"
    make_owner(app)
    response = post(client, "/login", {"email": "maria@example.com", "password": PASSWORD})
    assert "stickyminutes_session=" in response.headers["Set-Cookie"]
    client.set_cookie("session", "another-apps-cookie", domain="localhost")
    assert is_logged_in(client)


def test_a_password_change_logs_out_old_cookies(app):
    user_id, _ = make_owner(app)
    old = browser(app, user_id)
    with app.app_context():
        s = db.session()
        s.get(User, user_id).session_version += 1
        s.commit()
    assert not is_logged_in(old)


def test_create_owner_once(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-owner", "--name", "Maria Santos", "--email", "maria@example.com"],
                           input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0, result.output
    again = runner.invoke(args=["create-owner", "--name", "Ana", "--email", "ana@example.com"],
                          input=f"{PASSWORD}\n{PASSWORD}\n")
    assert again.exit_code != 0 and "already an owner" in again.output
    with app.app_context():
        workspace = db.session().scalar(select(Workspace))
        assert workspace.name == "Maria Santos's Meetings" and not workspace.is_demo


def test_try_the_demo_logs_in_to_a_sandbox_of_your_own(app, demo):
    client, workspace_id = demo
    page = client.get("/meetings", follow_redirects=True)
    assert "Demo" in words(page)
    with app.app_context():
        workspace = db.session().get(Workspace, workspace_id)
        assert workspace.is_demo and workspace.demo_expires_at > utcnow()


def test_nobody_can_log_in_to_a_demo_with_a_password(app, demo):
    _, workspace_id = demo
    with app.app_context():
        email = db.session().scalar(select(User.email).where(User.workspace_id == workspace_id))
    response = post(browser(app), "/login", {"email": email, "password": PASSWORD})
    assert response.status_code == 401


def test_an_old_demo_is_logged_out_and_deleted(app, demo):
    client, workspace_id = demo
    with app.app_context():
        s = db.session()
        s.get(Workspace, workspace_id).demo_expires_at = plus(utcnow(), seconds=-1)
        s.commit()
    assert not is_logged_in(client)
    with app.app_context():
        s = db.session()
        assert seed.purge(s, utcnow()) == 1
        s.commit()
        assert s.get(Workspace, workspace_id) is None
        assert s.scalar(select(User).where(User.workspace_id == workspace_id)) is None


def test_demo_ids_are_never_used_again(app):
    """A deleted demo's id must not go to the next one, or an old cookie would open it."""
    first = browser(app)
    post(first, "/demo")
    with first.session_transaction() as session:
        old_id = session["user_id"]
    with app.app_context():
        s = db.session()
        s.execute(Workspace.__table__.delete())
        s.commit()
    second = browser(app)
    post(second, "/demo")
    with second.session_transaction() as session:
        assert session["user_id"] != old_id
