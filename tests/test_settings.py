"""Settings: the account, the workspace, the Claude model, and what the demo can't change."""
from stickyminutes import db
from stickyminutes.models import Workspace

from .conftest import PASSWORD, is_logged_in, post, text, words


def test_settings_shows_every_section(owner):
    client, _ = owner
    page = words(client.get("/settings"))
    for heading in ("Your Account", "Workspace", "Claude Model", "Appearance", "Log Out"):
        assert heading in page


def test_change_the_workspace_and_model(app, owner):
    client, workspace_id = owner
    response = post(client, "/settings", {"action": "workspace", "name": "Team Meetings", "time_zone": "Asia/Tokyo"})
    assert response.status_code == 302
    response = post(client, "/settings", {"action": "model", "model": "claude-sonnet-5-5"})
    assert response.status_code == 302
    with app.app_context():
        workspace = db.session().get(Workspace, workspace_id)
        assert (workspace.name, workspace.time_zone, workspace.model) == ("Team Meetings", "Asia/Tokyo", "claude-sonnet-5-5")


def test_a_made_up_model_or_zone_is_refused(owner):
    client, _ = owner
    assert post(client, "/settings", {"action": "model", "model": "gpt-9"}).status_code == 400
    response = post(client, "/settings", {"action": "workspace", "name": "X", "time_zone": "Mars/Base"})
    assert response.status_code == 400 and "Choose a time zone" in text(response)


def test_changing_the_password_keeps_this_device_logged_in(owner):
    client, _ = owner
    response = post(client, "/settings", {"action": "password", "current_password": PASSWORD,
                                          "new_password": "new password 1", "confirm_password": "new password 1"})
    assert response.status_code == 302
    assert is_logged_in(client)


def test_the_demo_cant_change_its_account(demo):
    client, _ = demo
    assert post(client, "/settings", {"action": "name", "user_name": "Hacker"}).status_code == 403
    assert "can't change its account" in text(client.get("/settings"))
