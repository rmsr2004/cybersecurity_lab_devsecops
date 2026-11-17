import dataclasses
import functools
import pathlib
import typing

import flask

app = flask.Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"

# -----------------------------------------------------------------------------
# Intentionally small in-memory "database"
# -----------------------------------------------------------------------------

BASE_DIR = pathlib.Path(__file__).resolve().parent
MATERIALS_DIR = BASE_DIR / "materials"
MATERIALS_DIR.mkdir(exist_ok=True)

# Seed a couple of demo files.
(MATERIALS_DIR / "srs-summary.txt").write_text(
    "Secure Requirements Engineering summary", encoding="utf-8"
)
(MATERIALS_DIR / "secure-coding.txt").write_text(
    "Secure coding practices notes", encoding="utf-8"
)


@dataclasses.dataclass
class User:
    username: str
    password: str
    role: str
    student_id: typing.Optional[int] = None
    courses: typing.Optional[list[str]] = None


USERS = {
    "alice": User(username="alice", password="alicepw", role="student", student_id=1001),
    "bob": User(username="bob", password="bobpw", role="student", student_id=1002),
    "prof_srs": User(
        username="prof_srs", password="profpw", role="professor", courses=["SRS"]
    ),
    "admin1": User(username="admin1", password="adminpw", role="admin"),
}

STUDENT_PROFILES = {
    1001: {"student_id": 1001, "name": "Alice", "email": "alice@uc.pt", "program": "MEI"},
    1002: {"student_id": 1002, "name": "Bob", "email": "bob@uc.pt", "program": "MEI"},
}

GRADES = [
    {"student_id": 1001, "course_id": "SRS", "grade": 14},
    {"student_id": 1002, "course_id": "SRS", "grade": 15},
    {"student_id": 1001, "course_id": "SSD", "grade": 16},
]

def authenticated_user():
    """Resolve session identity against the server-side user directory."""
    username = flask.session.get("user")
    return USERS.get(username) if isinstance(username, str) else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if authenticated_user() is None:
            return {"error": "authentication required"}, 401
        return view(*args, **kwargs)
    return wrapped


def find_grade(student_id, course_id):
    for row in GRADES:
        if row["student_id"] == student_id and row["course_id"] == course_id:
            return row
    return None


# -----------------------------------------------------------------------------
# REST API Endpoints
# -----------------------------------------------------------------------------

@app.get("/")
def index():
    return {
        "message": "Baseline Secure Coding API",
        "endpoints": [
            "POST /login",
            "POST /logout",
            "GET /me",
            "GET /students/<student_id>/profile",
            "POST /grades/update",
            "GET /grades/<student_id>",
            "GET /files?path=<name>",
        ],
    }

@app.post("/login")
def login():
    username = flask.request.form.get("username", "")
    password = flask.request.form.get("password", "")

    user = USERS.get(username)
    if user is None or user.password != password:
        return {"error": "invalid credentials"}, 401

    flask.session["user"] = user.username
    flask.session["role"] = user.role
    flask.session["student_id"] = user.student_id
    flask.session["courses"] = user.courses or []

    return flask.redirect("/me")

@app.post("/logout")
def logout():
    flask.session.clear()
    return {"status": "logged out"}

@app.get("/me")
def me():
    if "user" not in flask.session:
        return {"user": None}

    return {
        "user": flask.session.get("user"),
        "role": flask.session.get("role"),
        "student_id": flask.session.get("student_id"),
        "courses": flask.session.get("courses"),
    }

@app.get("/students/<student_id>/profile")
@login_required
def get_profile(student_id):
    user = authenticated_user()
    try:
        sid = int(student_id)
    except (TypeError, ValueError):
        flask.abort(400)

    # Professors cannot read student profile records.
    if user.role == "professor" or (
        user.role == "student" and user.student_id != sid
    ):
        flask.abort(403)
    if user.role not in {"student", "admin"}:
        flask.abort(403)

    profile = STUDENT_PROFILES.get(sid)
    if profile is None:
        return {"error": "student not found"}, 404
    return flask.jsonify(profile)

@app.get("/grades/<student_id>")
@login_required
def get_grades(student_id):
    user = authenticated_user()
    try:
        sid = int(student_id)
    except (TypeError, ValueError):
        flask.abort(400)

    rows = [row for row in GRADES if row["student_id"] == sid]

    if user.role == "student":
        rows = rows if user.student_id == sid else []
    elif user.role == "professor":
        rows = [
            row for row in rows
            if row["course_id"] in (user.courses or [])
        ]
    elif user.role != "admin":
        rows = []

    # Never disclose an empty or unauthorized grade result.
    if not rows:
        flask.abort(403)
    return flask.jsonify(rows)

@app.post("/grades/update")
@login_required
def update_grade():
    # Authentication runs before request-body parsing.
    user = authenticated_user()
    data = flask.request.get_json(silent=True)
    if not isinstance(data, dict):
        flask.abort(400)
    try:
        student_id = int(data["student_id"])
        course_id = data["course_id"]
        grade = data["grade"]
    except (KeyError, TypeError, ValueError):
        flask.abort(400)

    if not isinstance(course_id, str) or not course_id:
        flask.abort(400)

    if user.role == "professor":
        if course_id not in (user.courses or []):
            flask.abort(403)
    elif user.role != "admin":
        flask.abort(403)

    if student_id not in STUDENT_PROFILES:
        flask.abort(404)

    row = find_grade(student_id, course_id)
    if row is None:
        GRADES.append({"student_id": student_id, "course_id": course_id, "grade": grade})
    else:
        row["grade"] = grade

    return {"status": "ok", "student_id": student_id, "course_id": course_id, "grade": grade}

@app.get("/files")
@login_required
def download_file():
    raw_path = flask.request.args.get("path", "")
    requested = pathlib.Path(raw_path)
    if requested.is_absolute():
        return {"error": "file not found"}, 404

    try:
        root = MATERIALS_DIR.resolve(strict=True)
        target = (root / requested).resolve(strict=True)
        target.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return {"error": "file not found"}, 404

    if not target.is_file():
        return {"error": "file not found"}, 404
    return flask.send_file(target)

@app.errorhandler(Exception)
def handle_error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return {"error": exc.description}, exc.code
    return {
        "error": str(exc),
        "type": exc.__class__.__name__,
    }, 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)