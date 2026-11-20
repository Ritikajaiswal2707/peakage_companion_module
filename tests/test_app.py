"""End-to-end tests: register, lessons, quiz pass/fail, attempt limit, admin reset and export."""
import itertools
import os
import re
import tempfile

_db_file = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"
os.environ["ADMIN_PHONES"] = "9000000001"
os.environ["REGISTRATION_CODE"] = "CODE1"
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.content import MODULES, load_modules  # noqa: E402
from app.main import app  # noqa: E402

FIRST, SECOND = MODULES[0], MODULES[1]
_phones = itertools.count(1)


def register(client, phone, name="Test Companion", code="CODE1"):
    return client.post("/register", data={
        "name": name, "phone": phone, "city": "Lucknow",
        "password": "secret1", "confirm": "secret1", "code": code,
    })


def view_all_lessons(client, module):
    for i in range(len(module.lessons)):
        assert client.get(f"/modules/{module.code}/lessons/{i}").status_code == 200


def take_quiz(client, module, correct: bool):
    page = client.get(f"/modules/{module.code}/quiz")
    assert page.status_code == 200, page.text
    attempt_id = re.search(r'name="attempt_id" value="(\d+)"', page.text).group(1)
    qids = re.findall(r'name="q_([^"]+)"', page.text)
    qids = list(dict.fromkeys(qids))
    data = {"attempt_id": attempt_id}
    for qid in qids:
        q = module.question_map[qid]
        data[f"q_{qid}"] = q.answer if correct else (q.answer + 1) % len(q.options)
    return client.post(f"/modules/{module.code}/quiz", data=data)


@pytest.fixture()
def companion():
    client = TestClient(app)
    phone = f"97{next(_phones):08d}"
    assert register(client, phone).status_code == 200
    return client


def test_all_content_files_are_valid():
    modules = load_modules()
    assert len(modules) >= 9
    for m in modules:
        assert len(m.questions) >= m.questions_per_quiz


def test_register_requires_code():
    client = TestClient(app)
    r = register(client, "9811111111", code="WRONG")
    assert "Wrong registration code" in r.text


def test_login_page_and_bad_login():
    client = TestClient(app)
    assert client.get("/login").status_code == 200
    r = client.post("/login", data={"phone": "9822222222", "password": "nope"})
    assert "Wrong mobile number or password" in r.text


def test_dashboard_requires_login():
    client = TestClient(app)
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_second_module_locked_until_first_passed(companion):
    r = companion.get(f"/modules/{SECOND.code}", follow_redirects=True)
    assert "Finish the previous module first" in r.text


def test_quiz_locked_until_lessons_viewed(companion):
    r = companion.get(f"/modules/{FIRST.code}/quiz", follow_redirects=True)
    assert "Open every lesson" in r.text


def test_pass_flow_unlocks_next_module(companion):
    view_all_lessons(companion, FIRST)
    r = take_quiz(companion, FIRST, correct=True)
    assert "You passed" in r.text and "100%" in r.text
    assert companion.get(f"/modules/{SECOND.code}").status_code == 200


def test_reload_quiz_keeps_same_questions(companion):
    view_all_lessons(companion, FIRST)
    a = companion.get(f"/modules/{FIRST.code}/quiz").text
    b = companion.get(f"/modules/{FIRST.code}/quiz").text
    assert re.findall(r'name="q_([^"]+)"', a) == re.findall(r'name="q_([^"]+)"', b)


def test_attempt_limit_then_admin_reset():
    client = TestClient(app)
    register(client, "9833333333", name="Blocked Person")
    view_all_lessons(client, FIRST)
    for _ in range(FIRST.max_attempts):
        r = take_quiz(client, FIRST, correct=False)
        assert "Almost there" in r.text or "Not passed" in r.text
    r = client.get(f"/modules/{FIRST.code}/quiz", follow_redirects=True)
    assert "used all your attempts" in r.text

    admin = TestClient(app)
    register(admin, "9000000001", name="Admin")
    page = admin.get("/admin")
    assert page.status_code == 200 and "Blocked Person" in page.text
    companion_id = re.search(r'/admin/companions/(\d+)">\s*<strong>Blocked Person', page.text).group(1)
    r = admin.post(f"/admin/companions/{companion_id}/reset", data={"module_code": FIRST.code}, follow_redirects=True)
    assert "Attempts reset" in r.text

    r = take_quiz(client, FIRST, correct=True)
    assert "You passed" in r.text

    csv_text = admin.get("/admin/export.csv").text
    assert "Blocked Person" in csv_text and "passed" in csv_text


def test_cannot_resubmit_same_attempt(companion):
    view_all_lessons(companion, FIRST)
    page = companion.get(f"/modules/{FIRST.code}/quiz").text
    attempt_id = re.search(r'name="attempt_id" value="(\d+)"', page).group(1)
    companion.post(f"/modules/{FIRST.code}/quiz", data={"attempt_id": attempt_id})
    r = companion.post(f"/modules/{FIRST.code}/quiz", data={"attempt_id": attempt_id}, follow_redirects=True)
    assert "already submitted" in r.text


def test_non_admin_blocked_from_admin(companion):
    assert companion.get("/admin").status_code == 403


def test_admin_password_reset_lets_companion_log_in():
    admin = TestClient(app)
    admin.post("/login", data={"phone": "9000000001", "password": "secret1"})
    other = TestClient(app)
    register(other, "9844444444", name="Forgetful")
    page = admin.get("/admin").text
    cid = re.search(r'/admin/companions/(\d+)">\s*<strong>Forgetful', page).group(1)
    admin.post(f"/admin/companions/{cid}/password", data={"new_password": "newpass9"})
    fresh = TestClient(app)
    r = fresh.post("/login", data={"phone": "+91 98444 44444", "password": "newpass9"}, follow_redirects=True)
    assert "<h1>Forgetful</h1>" in r.text


def test_interactive_answer_api_locks_first_answer(companion):
    view_all_lessons(companion, FIRST)
    page = companion.get(f"/modules/{FIRST.code}/quiz").text
    attempt_id = re.search(r'name="attempt_id" value="(\d+)"', page).group(1)
    qids = list(dict.fromkeys(re.findall(r'name="q_([^"]+)"', page)))
    q = FIRST.question_map[qids[0]]
    wrong = (q.answer + 1) % len(q.options)

    r = companion.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": q.id, "choice": wrong})
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is False and body["correct_choice"] == q.answer and body["answered"] == 1

    # changing the answer afterwards is not allowed: the first answer stays
    r = companion.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": q.id, "choice": q.answer})
    assert r.json()["correct"] is False

    # answer the rest correctly through the API, then finish with an empty form
    for qid in qids[1:]:
        ans = FIRST.question_map[qid].answer
        assert companion.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": qid, "choice": ans}).json()["correct"]
    r = companion.post(f"/modules/{FIRST.code}/quiz", data={"attempt_id": attempt_id})
    expected = round(100 * (len(qids) - 1) / len(qids))
    assert f"{expected}%" in r.text

    # reloading the quiz page shows answered questions locked
    # (attempt is submitted, so the API refuses further answers)
    r = companion.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": qids[1], "choice": 0})
    assert r.status_code == 409


def test_api_rejects_other_users_attempt(companion):
    view_all_lessons(companion, FIRST)
    page = companion.get(f"/modules/{FIRST.code}/quiz").text
    attempt_id = re.search(r'name="attempt_id" value="(\d+)"', page).group(1)
    stranger = TestClient(app)
    register(stranger, "9855555555", name="Stranger")
    r = stranger.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": "x", "choice": 0})
    assert r.status_code == 409


def test_certificate_after_all_modules_and_offline_steps():
    from app.content import OFFLINE_STEPS

    client = TestClient(app)
    register(client, "9866666666", name="Future Star")
    assert "unlocks" in client.get("/certificate", follow_redirects=True).text
    for module in MODULES:
        view_all_lessons(client, module)
        assert "You passed" in take_quiz(client, module, correct=True).text

    admin = TestClient(app)
    admin.post("/login", data={"phone": "9000000001", "password": "secret1"})
    page = admin.get("/admin").text
    cid = re.search(r'/admin/companions/(\d+)">\s*<strong>Future Star', page).group(1)
    for step in OFFLINE_STEPS:
        r = admin.post(f"/admin/companions/{cid}/offline", data={"step_code": step.code, "done": "1"}, follow_redirects=True)
    assert "certified go-solo companion" in r.text

    cert_page = client.get("/certificate").text
    code = re.search(r"(PA-[0-9A-F]{8})", cert_page).group(1)
    assert "Future Star" in cert_page
    verify = TestClient(app).get(f"/verify/{code}").text
    assert "Valid certificate" in verify and "Future Star" in verify
    assert "Not found" in TestClient(app).get("/verify/PA-00000000").text
