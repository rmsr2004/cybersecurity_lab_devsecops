import copy

import baseline_secure_coding_api as api


def login(client, username, password):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert response.get_json()["user"] == username

def update(client, student_id, course_id, grade):
    return client.post(
        "/grades/update",
        json={"student_id": student_id, "course_id": course_id, "grade": grade},
    )

def snapshot():
    return copy.deepcopy(api.GRADES)

def test_assigned_professor_can_update_grade(client):
    login(client, "prof_srs", "profpw")
    response = client.post(
        "/grades/update",
        json={"student_id": 1001, "course_id": "SRS", "grade": 18},
    )
    assert response.status_code == 200
    assert api.find_grade(1001, "SRS")["grade"] == 18

def test_admin_can_update_grade_in_any_course(client):
    login(client, "admin1", "adminpw")
    response = update(client, 1001, "SSD", 19)
    assert response.status_code == 200
    assert api.find_grade(1001, "SSD")["grade"] == 19

def test_unauthenticated_update_is_rejected_with_401(client):
    before = snapshot()
    response = update(client, 1001, "SRS", 20)
    assert response.status_code == 401
    assert api.GRADES == before


def test_student_cannot_update_own_grade(client):
    login(client, "alice", "alicepw")
    before = snapshot()
    response = update(client, 1001, "SRS", 20)
    assert response.status_code == 403
    assert api.GRADES == before

def test_student_cannot_update_another_students_grade(client):
    login(client, "alice", "alicepw")
    before = snapshot()
    response = update(client, 1002, "SRS", 0)
    assert response.status_code == 403
    assert api.GRADES == before


def test_professor_cannot_update_unassigned_course(client):
    login(client, "prof_srs", "profpw")
    before = snapshot()
    response = update(client, 1001, "SSD", 0)
    assert response.status_code == 403
    assert api.find_grade(1001, "SSD")["grade"] == 16
    assert api.GRADES == before


def test_professor_cannot_create_record_in_unassigned_course(client):
    login(client, "prof_srs", "profpw")
    before = snapshot()
    response = update(client, 1002, "SSD", 20)
    assert response.status_code == 403
    assert api.find_grade(1002, "SSD") is None
    assert len(api.GRADES) == len(before)


def test_session_is_not_valid_after_logout(client):
    login(client, "prof_srs", "profpw")
    assert client.post("/logout").status_code == 200
    before = snapshot()
    response = update(client, 1001, "SRS", 20)
    assert response.status_code == 401
    assert api.GRADES == before


def test_unauthenticated_malformed_body_is_401_not_500(client):
    response = client.post(
        "/grades/update", data="not json", content_type="text/plain"
    )
    assert response.status_code == 401