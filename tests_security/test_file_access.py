import os

import pytest

import baseline_secure_coding_api as api

OUTSIDE_SECRET = "OUTSIDE-SECRET-CONTENT"
SIBLING_SECRET = "SIBLING-DIRECTORY-SECRET"
INSIDE_TEXT = "inside materials content"


def login(client, username="alice", password="alicepw"):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert response.get_json()["user"] == username


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    materials = tmp_path / "materials"
    (materials / "sub").mkdir(parents=True)
    (materials / "notes.txt").write_text(INSIDE_TEXT, encoding="utf-8")
    (materials / "sub" / "inner.txt").write_text(INSIDE_TEXT, encoding="utf-8")

    outside = tmp_path / "secret.txt"
    outside.write_text(OUTSIDE_SECRET, encoding="utf-8")

    sibling = tmp_path / "materials_evil"
    sibling.mkdir()
    (sibling / "leak.txt").write_text(SIBLING_SECRET, encoding="utf-8")

    monkeypatch.setattr(api, "MATERIALS_DIR", materials)
    return {"materials": materials, "outside": outside, "sibling": sibling}


def assert_denied_without_leak(response):
    body = response.get_data(as_text=True)
    assert OUTSIDE_SECRET not in body
    assert SIBLING_SECRET not in body
    assert 400 <= response.status_code < 500


def test_authenticated_user_can_download_file_inside_materials(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "notes.txt"})
    assert response.status_code == 200
    assert response.get_data(as_text=True) == INSIDE_TEXT


def test_authenticated_user_can_download_file_in_subdirectory(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "sub/inner.txt"})
    assert response.status_code == 200
    assert response.get_data(as_text=True) == INSIDE_TEXT


def test_path_with_dotdot_that_stays_inside_is_still_served(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "sub/../notes.txt"})
    assert response.status_code == 200
    assert response.get_data(as_text=True) == INSIDE_TEXT


def test_unauthenticated_download_is_rejected_with_401(client, sandbox):
    response = client.get("/files", query_string={"path": "notes.txt"})
    assert response.status_code == 401
    assert INSIDE_TEXT not in response.get_data(as_text=True)


def test_parent_directory_traversal_is_denied(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "../secret.txt"})
    assert_denied_without_leak(response)


def test_nested_traversal_is_denied(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "sub/../../secret.txt"})
    assert_denied_without_leak(response)


def test_url_encoded_traversal_is_denied(client, sandbox):
    login(client)
    response = client.get("/files?path=..%2fsecret.txt")
    assert_denied_without_leak(response)


def test_absolute_path_is_denied(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": str(sandbox["outside"])})
    assert_denied_without_leak(response)


def test_sibling_directory_with_same_prefix_is_denied(client, sandbox):
    login(client)
    response = client.get("/files", query_string={"path": "../materials_evil/leak.txt"})
    assert_denied_without_leak(response)


def test_symlink_pointing_outside_is_denied(client, sandbox):
    link = sandbox["materials"] / "link.txt"
    try:
        os.symlink(sandbox["outside"], link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    login(client)
    response = client.get("/files", query_string={"path": "link.txt"})
    assert_denied_without_leak(response)
