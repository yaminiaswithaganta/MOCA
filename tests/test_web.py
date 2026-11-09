"""
Tests for the web app's accounts, access rules and test flow.

    python -m unittest tests/test_web.py -v

Runs on a throwaway SQLite database with locally signed tokens, so it needs
neither Supabase nor a microphone. Above all it checks who can see what.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

_tmp = tempfile.TemporaryDirectory()
SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER_URL = "https://test.supabase.co"
os.environ.update(MOCA_DATABASE_URL=f"sqlite:///{_tmp.name}/test.db", MOCA_SUPABASE_URL=ISSUER_URL,
                  MOCA_SUPABASE_JWT_SECRET=SECRET, MOCA_SUPABASE_SERVICE_KEY="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import jwt  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from moca_tasks import ALL_TASKS  # noqa: E402
from webapp import listen, sessions, supabase_admin  # noqa: E402
from webapp import web_tasks as wt  # noqa: E402
from webapp.db import SessionLocal, TestSession, User, init_db  # noqa: E402
from webapp.server import app  # noqa: E402

init_db()
sessions.RESULTS_ROOT = Path(_tmp.name) / "results"
sessions.RESULTS_ROOT.mkdir()
client = TestClient(app)
_n = [0]


def token(sub, email="a@example.com", secret=SECRET, aud="authenticated", iss=f"{ISSUER_URL}/auth/v1",
          exp=4102444800, alg="HS256"):
    return jwt.encode({"sub": sub, "email": email, "aud": aud, "iss": iss, "exp": exp}, secret, algorithm=alg)


class Who:
    """One signed-in person calling the API."""

    def __init__(self):
        _n[0] += 1
        self.id = f"00000000-0000-0000-0000-{_n[0]:012d}"
        self.headers = {"Authorization": f"Bearer {token(self.id)}"}

    def get(self, url):
        return client.get(url, headers=self.headers)

    def post(self, url, body=None):
        return client.post(url, headers=self.headers, json=body if body is not None else {})

    def put(self, url, body):
        return client.put(url, headers=self.headers, json=body)

    def patch(self, url, body):
        return client.patch(url, headers=self.headers, json=body)

    def delete(self, url):
        return client.delete(url, headers=self.headers)


def new_patient(education=10):
    w = Who()
    r = w.post("/api/me/onboard", {"name": f"Patient {w.id[-3:]}", "date_of_birth": "1950-02-03",
                                   "sex": "Female", "education_years": education})
    assert r.status_code == 200, r.text
    return w


def new_admin():
    w = Who()
    with SessionLocal() as db:
        db.add(User(id=w.id, email=f"{w.id}@example.com", role="admin"))
        db.commit()
    return w


def add_person(admin, kind, **details):
    """An admin adds someone with a password. Supabase's login is replaced by a known user id."""
    w = Who()
    body = {"email": f"{w.id}@example.com", "name": f"{kind} {w.id[-3:]}", "password": "Secret-123", **details}
    with mock.patch.object(supabase_admin, "create_login", return_value=w.id) as create:
        w.added = admin.post(f"/api/admin/{kind}s", body)
    w.create = create
    return w


def new_examiner():
    w = add_person(new_admin(), "examiner", title="Neurologist")
    assert w.added.status_code == 200, w.added.text
    w.standard = w.get("/api/templates").json()[0]
    return w


def start(patient, template_id):
    r = patient.post("/api/sessions", {"template_id": template_id, "consent": True,
                                       "timezone": "Asia/Kolkata"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def finished_test(patient, examiner):
    """A finished test: every task skipped (0 points)."""
    sid = start(patient, examiner.standard["id"])
    for n in ALL_TASKS:
        assert patient.post(f"/api/sessions/{sid}/tasks/{n}/skip").status_code == 200
    assert patient.post(f"/api/sessions/{sid}/finish").status_code == 200
    return sid


class TestTokens(unittest.TestCase):
    def call(self, tok):
        return client.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).status_code

    def test_good_token(self):
        self.assertEqual(self.call(token("u1")), 200)

    def test_rejected_tokens(self):
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(self.call("not-a-token"), 401)
        self.assertEqual(self.call(token("u1", secret="x" * 40)), 401)     # forged
        self.assertEqual(self.call(token("u1", exp=1000)), 401)            # expired
        self.assertEqual(self.call(token("u1", aud="anon")), 401)          # not a user's token
        self.assertEqual(self.call(token("u1", iss="https://evil.example/auth/v1")), 401)

    def test_unsigned_token_is_rejected(self):
        tok = jwt.encode({"sub": "u1", "aud": "authenticated", "iss": f"{ISSUER_URL}/auth/v1"},
                         None, algorithm="none")
        self.assertEqual(self.call(tok), 401)

    def test_everything_private_needs_a_login(self):
        for url in ("/api/config", "/api/sessions", "/api/sessions/1", "/api/templates",
                    "/api/patients", "/api/stats", "/api/examiners",
                    "/api/sessions/1/files/a.wav"):
            self.assertEqual(client.get(url).status_code, 401, url)
        self.assertEqual(client.post("/api/face").status_code, 401)

    def test_old_open_results_folder_is_gone(self):
        real = sessions.RESULTS_ROOT / "session_x"
        real.mkdir(exist_ok=True)
        (real / "task1_audio.wav").write_bytes(b"PRIVATE-RECORDING")
        r = client.get("/results/session_x/task1_audio.wav")     # at most the app's own page
        self.assertNotIn(b"PRIVATE-RECORDING", r.content)
        self.assertNotIn("audio", r.headers.get("content-type", ""))


class TestOnboarding(unittest.TestCase):
    def test_signing_up_only_ever_makes_a_patient(self):
        w = Who()
        r = w.post("/api/me/onboard", {"name": "Dr Fake", "role": "examiner", "invite_code": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(w.get("/api/me").json()["role"], "patient")

    def test_setup_happens_once(self):
        p = new_patient()
        self.assertEqual(p.post("/api/me/onboard", {"name": "Again"}).status_code, 409)

    def test_examiner_starts_with_the_standard_test(self):
        t = new_examiner().standard
        self.assertEqual(t["tasks"], ALL_TASKS)
        self.assertEqual(t["max_points"], 30)
        self.assertTrue(t["published"] and t["standard"])

    def test_profile_validation(self):
        p = new_patient()
        self.assertEqual(p.put("/api/me/profile", {"name": ""}).status_code, 400)
        self.assertEqual(p.put("/api/me/profile", {"name": "A", "education_years": 99}).status_code, 400)
        self.assertEqual(p.put("/api/me/profile", {"name": "A", "date_of_birth": "2999-01-01"}).status_code, 400)
        self.assertEqual(p.put("/api/me/profile", {"education_years": "x"}).status_code, 400)
        r = p.put("/api/me/profile", {"name": "New Name", "education_years": 16})
        self.assertEqual(r.json()["profile"]["name"], "New Name")


class TestTemplates(unittest.TestCase):
    def test_design_rules(self):
        e = new_examiner()
        ok = {"name": "Memory check", "tasks": [5, 4, 12]}
        for bad, why in (({**ok, "name": " "}, "name"), ({**ok, "tasks": []}, "no tasks"),
                         ({**ok, "tasks": [1, 1]}, "repeated"), ({**ok, "tasks": [14]}, "unknown"),
                         ({**ok, "tasks": [12]}, "recall without memory"),
                         ({**ok, "tasks": [12, 5]}, "recall before memory")):
            self.assertEqual(e.post("/api/templates", bad).status_code, 400, why)
        r = e.post("/api/templates", {**ok, "settings": {"extra_answer_seconds": 99}})
        self.assertEqual(r.status_code, 422)
        r = e.post("/api/templates", ok).json()
        self.assertEqual(r["tasks"], [5, 4, 12])              # the order is kept
        self.assertEqual(r["max_points"], 8)
        self.assertFalse(r["published"] or r["standard"])

    def test_only_the_owner_can_touch_a_template(self):
        a, b = new_examiner(), new_examiner()
        t = a.standard["id"]
        self.assertEqual(b.get(f"/api/templates/{t}").status_code, 404)
        self.assertEqual(b.put(f"/api/templates/{t}", {"name": "x", "tasks": [1]}).status_code, 404)
        self.assertEqual(b.delete(f"/api/templates/{t}").status_code, 404)
        self.assertNotIn(t, [x["id"] for x in b.get("/api/templates").json()])

    def test_patients_cannot_design_tests(self):
        p = new_patient()
        self.assertEqual(p.get("/api/templates").status_code, 403)
        self.assertEqual(p.post("/api/templates", {"name": "x", "tasks": [1]}).status_code, 403)

    def test_patients_see_only_published_tests(self):
        e = new_examiner()
        draft = e.post("/api/templates", {"name": "Draft", "tasks": [1]}).json()
        p = new_patient()
        mine = next(x for x in p.get("/api/examiners").json() if x["id"] == e.standard["examiner_id"])
        self.assertEqual([t["name"] for t in mine["tests"]], ["Standard MoCA"])
        self.assertEqual(p.post("/api/sessions", {"template_id": draft["id"], "consent": True}).status_code, 404)

    def test_archived_template_keeps_past_tests(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        e.delete(f"/api/templates/{e.standard['id']}")
        self.assertEqual(p.get(f"/api/sessions/{sid}").json()["template_name"], "Standard MoCA")
        self.assertEqual(p.post("/api/sessions", {"template_id": e.standard["id"], "consent": True}).status_code, 404)

    def test_editing_a_template_does_not_change_a_test_in_progress(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        e.put(f"/api/templates/{e.standard['id']}", {"name": "Short", "tasks": [1]})
        s = p.get(f"/api/sessions/{sid}").json()
        self.assertEqual(s["tasks"], ALL_TASKS)


class TestStartingATest(unittest.TestCase):
    def test_consent_is_required(self):
        e, p = new_examiner(), new_patient()
        r = p.post("/api/sessions", {"template_id": e.standard["id"], "consent": False})
        self.assertEqual(r.status_code, 400)

    def test_education_is_required(self):
        e, p = new_examiner(), new_patient(education=None)
        r = p.post("/api/sessions", {"template_id": e.standard["id"], "consent": True})
        self.assertEqual(r.status_code, 400)

    def test_examiners_cannot_start_tests(self):
        e = new_examiner()
        r = e.post("/api/sessions", {"template_id": e.standard["id"], "consent": True})
        self.assertEqual(r.status_code, 403)

    def test_custom_order_is_followed(self):
        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "O", "tasks": [13, 5, 12], "published": True}).json()
        self.assertEqual(p.get(f"/api/sessions/{start(p, t['id'])}").json()["tasks"], [13, 5, 12])

    def test_a_task_outside_the_test_is_refused(self):
        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "One", "tasks": [1], "published": True}).json()
        sid = start(p, t["id"])
        self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/4/skip").status_code, 400)


class TestPatientPrivacy(unittest.TestCase):
    def test_patients_cannot_reach_each_other(self):
        e, a, b = new_examiner(), new_patient(), new_patient()
        sid = start(a, e.standard["id"])
        self.assertEqual(b.get(f"/api/sessions/{sid}").status_code, 404)
        self.assertEqual(b.post(f"/api/sessions/{sid}/tasks/1/skip").status_code, 404)
        self.assertEqual(b.post(f"/api/sessions/{sid}/finish").status_code, 404)
        self.assertEqual(b.get("/api/sessions").json(), [])

    def test_examiners_cannot_reach_each_others_patients(self):
        e, other, p = new_examiner(), new_examiner(), new_patient()
        sid = finished_test(p, e)
        pid = e.get(f"/api/sessions/{sid}").json()["patient"]["id"]
        self.assertEqual(other.get(f"/api/sessions/{sid}").status_code, 404)
        self.assertEqual(other.get(f"/api/patients/{pid}").status_code, 404)
        self.assertEqual(other.post(f"/api/sessions/{sid}/release", {}).status_code, 404)
        self.assertEqual(other.delete(f"/api/sessions/{sid}").status_code, 404)
        self.assertEqual(other.get("/api/patients").json(), [])
        self.assertEqual(other.get("/api/stats").json()["patients"], 0)

    def test_patients_get_no_examiner_views(self):
        p = new_patient()
        self.assertEqual(p.get("/api/patients").status_code, 403)
        self.assertEqual(p.get("/api/stats").status_code, 403)

    def test_examiner_list_shows_no_private_details(self):
        new_examiner()
        for e in new_patient().get("/api/examiners").json():
            self.assertEqual(set(e), {"id", "name", "title", "organization", "tests"})

    def test_evidence_files_are_examiner_only(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        with SessionLocal() as db:
            s = db.get(TestSession, sid)
            wav = Path(s.folder) / "task4_naming_lion.wav"
            wav.write_bytes(b"RIFF")
            (Path(s.folder) / "patient.json").write_text("{}")
            s.results[0].evidence_files = [str(wav)]
            db.commit()
        url = f"/api/sessions/{sid}/files/task4_naming_lion.wav"
        self.assertEqual(e.get(url).content, b"RIFF")
        self.assertEqual(p.get(url).status_code, 403)
        self.assertEqual(new_examiner().get(url).status_code, 404)
        self.assertEqual(e.get(f"/api/sessions/{sid}/files/patient.json").status_code, 404)    # not listed
        self.assertEqual(e.get(f"/api/sessions/{sid}/files/..%2F..%2Fmoca_common.py").status_code, 404)


class TestScoresStayHidden(unittest.TestCase):
    SCORE_FIELDS = ("result", "report", "sheet", "total", "adjusted_total", "score")

    def assert_no_scores(self, data):
        for field in self.SCORE_FIELDS:
            self.assertNotIn(field, data)

    def test_no_score_in_any_answer_until_release(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        self.assert_no_scores(p.post(f"/api/sessions/{sid}/tasks/1/skip").json())
        for n in ALL_TASKS[1:]:
            p.post(f"/api/sessions/{sid}/tasks/{n}/skip")
        self.assert_no_scores(p.post(f"/api/sessions/{sid}/finish").json())
        got = p.get(f"/api/sessions/{sid}").json()
        self.assert_no_scores(got)
        self.assertEqual(got["stage"], "awaiting_review")
        self.assert_no_scores(p.get("/api/sessions").json()[0])

    def test_score_appears_after_release(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        self.assertEqual(e.post(f"/api/sessions/{sid}/release", {"note": "See you soon"}).status_code, 200)
        got = p.get(f"/api/sessions/{sid}").json()
        self.assertEqual(got["stage"], "released")
        self.assertEqual(got["result"]["note"], "See you soon")
        self.assertEqual(got["result"]["max_total"], 30)
        self.assertNotIn("report", got)                    # no transcripts or recordings

    def test_finished_test_cannot_be_retaken(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/1/skip").status_code, 409)
        self.assertEqual(p.post(f"/api/sessions/{sid}/finish").status_code, 409)


class TestCameraTasks(unittest.TestCase):
    def one_task(self, number):
        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "T", "tasks": [number], "published": True}).json()
        return e, p, start(p, t["id"])

    def photo(self):
        ok, png = cv2.imencode(".png", np.full((480, 640, 3), 255, np.uint8))
        return {"file": ("capture.png", png.tobytes(), "image/png")}

    def test_drawing_photo_is_saved_and_scored_for_the_examiner_only(self):
        for number, name in ((2, "task2_cube_copy"), (3, "task3_clock_draw")):
            e, p, sid = self.one_task(number)
            r = client.post(f"/api/sessions/{sid}/tasks/{number}/photo", headers=p.headers, files=self.photo())
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {"task": name, "saved": True})
            s = e.get(f"/api/sessions/{sid}").json()
            urls = s["report"]["tasks"][name]["evidence_urls"]
            self.assertTrue(urls)
            self.assertEqual(e.get(urls[0]).status_code, 200)

    def test_bad_photo(self):
        _, p, sid = self.one_task(2)
        r = client.post(f"/api/sessions/{sid}/tasks/2/photo", headers=p.headers,
                        files={"file": ("x.png", b"not an image", "image/png")})
        self.assertEqual(r.status_code, 400)

    def test_oversized_photo(self):
        _, p, sid = self.one_task(2)
        with mock.patch.object(sessions, "MAX_PHOTO_BYTES", 10):
            r = client.post(f"/api/sessions/{sid}/tasks/2/photo", headers=p.headers, files=self.photo())
        self.assertEqual(r.status_code, 413)

    def test_letters_are_saved_and_scored_for_the_examiner_only(self):
        e, p, sid = self.one_task(7)
        times = [i * wt.t7.LETTER_INTERVAL_S for i in range(len(wt.t7.LETTERS))]
        raises = [t + 0.5 for t, letter in zip(times, wt.t7.LETTERS) if letter == "A"]
        r = p.post(f"/api/sessions/{sid}/tasks/7/letters", {
            "letter_times": times, "raise_times": raises, "up_samples": [], "mode": "keyboard",
            "calibration": {}, "trace": []})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"task": "task7_letters", "saved": True})
        p.post(f"/api/sessions/{sid}/finish")
        self.assertEqual(e.get(f"/api/sessions/{sid}").json()["report"]["tasks"]["task7_letters"]["score"], 1)

    def test_a_patient_cannot_send_to_someone_elses_test(self):
        _, _, sid = self.one_task(2)
        other = new_patient()
        r = client.post(f"/api/sessions/{sid}/tasks/2/photo", headers=other.headers, files=self.photo())
        self.assertEqual(r.status_code, 404)


class TestReview(unittest.TestCase):
    def test_correction_changes_the_total_and_keeps_the_original(self):
        e, p = new_examiner(), new_patient(education=10)
        sid = finished_test(p, e)
        crit = {"lion": 1, "rhino": 1, "camel": 0}
        s = e.patch(f"/api/sessions/{sid}/tasks/4", {"criteria": crit, "note": "Rhino was clear"}).json()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["adjusted_total"], 3)           # + the education point
        t = s["report"]["tasks"]["task4_naming"]
        self.assertEqual((t["score"], t["auto_score"]), (2, 0))
        self.assertEqual(t["correction_note"], "Rhino was clear")
        s = e.patch(f"/api/sessions/{sid}/tasks/1", {"score": 1, "note": "Path was right"}).json()
        self.assertEqual(s["total"], 3)
        s = e.patch(f"/api/sessions/{sid}/tasks/4", {"criteria": {**crit, "camel": 1}, "note": "All"}).json()
        self.assertEqual(s["report"]["tasks"]["task4_naming"]["auto_score"], 0)    # still the original

    def test_bad_corrections(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        for number, body, code in ((4, {"criteria": {"lion": 1}, "note": "x"}, 400),
                                   (4, {"criteria": {"lion": 5, "rhino": 0, "camel": 0}, "note": "x"}, 400),
                                   (1, {"score": 2, "note": "x"}, 400), (1, {"note": "x"}, 400),
                                   (5, {"score": 0, "note": "x"}, 400), (1, {"score": 1, "note": ""}, 422)):
            self.assertEqual(e.patch(f"/api/sessions/{sid}/tasks/{number}", body).status_code, code, body)

    def test_released_results_are_final(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        e.post(f"/api/sessions/{sid}/release", {})
        self.assertEqual(e.patch(f"/api/sessions/{sid}/tasks/1", {"score": 1, "note": "x"}).status_code, 409)
        self.assertEqual(e.post(f"/api/sessions/{sid}/release", {}).status_code, 409)

    def test_unfinished_test_cannot_be_released(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        self.assertEqual(e.post(f"/api/sessions/{sid}/release", {}).status_code, 409)

    def test_patient_cannot_review(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        self.assertEqual(p.post(f"/api/sessions/{sid}/release", {}).status_code, 403)
        self.assertEqual(p.patch(f"/api/sessions/{sid}/tasks/1", {"score": 1, "note": "x"}).status_code, 403)
        self.assertEqual(p.delete(f"/api/sessions/{sid}").status_code, 403)

    def test_partial_test_gets_no_education_point(self):
        e, p = new_examiner(), new_patient(education=8)
        t = e.post("/api/templates", {"name": "Short", "tasks": [1], "published": True}).json()
        sid = start(p, t["id"])
        p.post(f"/api/sessions/{sid}/tasks/1/skip")
        p.post(f"/api/sessions/{sid}/finish")
        s = e.get(f"/api/sessions/{sid}").json()
        self.assertEqual((s["education_bonus"], s["max_total"]), (0, 1))

    def test_delete_removes_the_files(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        with SessionLocal() as db:
            folder = Path(db.get(TestSession, sid).folder)
        self.assertTrue(folder.is_dir())
        self.assertEqual(e.delete(f"/api/sessions/{sid}").status_code, 200)
        self.assertFalse(folder.exists())
        self.assertEqual(e.get(f"/api/sessions/{sid}").status_code, 404)

    def test_stats(self):
        e, p = new_examiner(), new_patient()
        a, b = finished_test(p, e), finished_test(p, e)
        e.post(f"/api/sessions/{b}/release", {})
        start(p, e.standard["id"])
        s = e.get("/api/stats").json()
        self.assertEqual((s["patients"], s["awaiting_review"], s["released"], s["in_progress"]), (1, 1, 1, 1))
        self.assertTrue(a)


class TestOrientationTimeZone(unittest.TestCase):
    def test_date_is_judged_where_the_patient_is(self):
        """The year rolls over for the patient while it is still the old year on the server."""
        fixed = datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)       # 1 Jan 2027 in Kolkata

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "Orientation", "tasks": [13], "published": True}).json()
        sid = start(p, t["id"])
        said = {it["key"]: {"phrases": [{"text": "x"}], "final": {"text": "x"}, "end_reason": "t", "wav": "x.wav"}
                for it in wt.t13.build_items(fixed.astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None))}
        said["year"]["final"]["text"] = "two thousand twenty seven"
        said["month"]["final"]["text"] = "January"
        for step, answer in said.items():
            listen.save_answer(sid, 13, step, answer)
        with mock.patch.object(sessions, "datetime", Clock):
            self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/13/finish").status_code, 200)
        p.post(f"/api/sessions/{sid}/finish")
        crit = e.get(f"/api/sessions/{sid}").json()["report"]["tasks"]["task13_orientation"]["criteria"]
        self.assertEqual((crit["year"], crit["month"]), (1, 1))


class TestListeningSocket(unittest.TestCase):
    def first_message(self, init):
        with client.websocket_connect("/ws/listen") as ws:
            ws.send_json(init)
            return ws.receive_json()

    def test_needs_a_valid_token(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        init = {"session_id": sid, "task": 4, "step": "lion"}
        for tok in (None, "bad", token("someone", secret="y" * 40)):
            self.assertEqual(self.first_message({**init, "token": tok})["type"], "error")

    def test_only_the_tests_patient_can_listen(self):
        e, p, other = new_examiner(), new_patient(), new_patient()
        sid = start(p, e.standard["id"])
        init = {"session_id": sid, "task": 4, "step": "lion"}
        for who in (other, e):
            msg = self.first_message({**init, "token": token(who.id)})
            self.assertEqual(msg, {"type": "error", "text": "bad request: test or task not found"})

    def test_finished_test_is_closed(self):
        e, p = new_examiner(), new_patient()
        sid = finished_test(p, e)
        msg = self.first_message({"session_id": sid, "task": 4, "step": "lion", "token": token(p.id)})
        self.assertEqual(msg["type"], "error")


class TestNoSound(unittest.TestCase):
    def setUp(self):
        e, p = new_examiner(), new_patient()
        self.sid = start(p, e.standard["id"])
        self.folder = tempfile.mkdtemp()

    def run_worker(self, chunk):
        rec, sent = listen.StreamRecorder(), []
        if chunk:
            rec.push(chunk)
        answer = {"phrases": [], "final": None, "end_reason": "no answer", "wav": "x.wav"}
        with mock.patch.object(listen, "engine"), \
                mock.patch.object(listen, "_listen_answer", return_value=(answer, {"type": "done"})):
            listen._listen_worker(self.sid, 4, "lion", self.folder, 0, rec, sent.append,
                                  threading.Event(), threading.Event())
        stored = listen.answers_for(self.sid, 4).get("lion")
        return sent[-1], stored

    def test_no_audio_is_an_error_and_is_never_scored(self):
        msg, stored = self.run_worker(b"")
        self.assertEqual(msg["type"], "error")
        self.assertIn("microphone", msg["text"])
        self.assertIsNone(stored)

    def test_silence_from_a_working_microphone_still_counts(self):
        msg, stored = self.run_worker(np.zeros(1600, np.float32).tobytes())
        self.assertEqual(msg["type"], "done")
        self.assertIsNotNone(stored)


class TestPendingAnswers(unittest.TestCase):
    """Answers of a task in progress live in the database, so any server copy can score the task."""

    def test_saved_answers_survive_and_are_cleared(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        listen.save_answer(sid, 4, "lion", {"phrases": [{"text": "lion"}], "final": None, "end_reason": "x",
                                            "wav": "a.wav", "result": (1, "ok", {"n": 2})})
        listen.save_answer(sid, 4, "lion", {"phrases": [], "final": {"text": "a lion"}, "end_reason": "y", "wav": "b.wav"})
        listen.save_answer(sid, 6, "forward", {"phrases": [], "final": None, "end_reason": "z", "wav": "c.wav"})
        got = listen.answers_for(sid, 4)
        self.assertEqual(list(got), ["lion"])
        self.assertEqual(got["lion"]["final"]["text"], "a lion")         # a retry replaces the answer
        listen.clear_answers(sid, 4)
        self.assertEqual(listen.answers_for(sid, 4), {})
        self.assertIn("forward", listen.answers_for(sid, 6))

    def test_task_one_result_survives_the_database(self):
        """Task 1 stores (score, reason, details); it comes back as a list and still scores."""
        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "Trail", "tasks": [1], "published": True}).json()
        sid = start(p, t["id"])
        details = {"spoken_sequence": ["1", "A"], "final_transcript": "one a", "end_reason": "x"}
        listen.save_answer(sid, 1, "path", {"result": (0, "incomplete", details), "wav": "t.wav", "transcript": "t.json"})
        self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/1/finish").status_code, 200)
        self.assertEqual(listen.answers_for(sid, 1), {})
        p.post(f"/api/sessions/{sid}/finish")
        r = e.get(f"/api/sessions/{sid}").json()["report"]["tasks"]["task1_trail_making"]
        self.assertEqual((r["score"], r["reason"]), (0, "incomplete"))

    def test_finishing_or_deleting_clears_them(self):
        e, p = new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        listen.save_answer(sid, 4, "lion", {"phrases": [], "final": None, "end_reason": "x", "wav": "a.wav"})
        p.post(f"/api/sessions/{sid}/finish")
        self.assertEqual(listen.answers_for(sid, 4), {})
        sid = start(p, e.standard["id"])
        listen.save_answer(sid, 4, "lion", {"phrases": [], "final": None, "end_reason": "x", "wav": "a.wav"})
        p.post(f"/api/sessions/{sid}/finish")
        self.assertEqual(e.delete(f"/api/sessions/{sid}").status_code, 200)

    def test_scoring_works_without_the_original_folder(self):
        """A fresh server copy has no results folder: scoring must make it."""
        e, p = new_examiner(), new_patient()
        t = e.post("/api/templates", {"name": "Recall", "tasks": [5, 12], "published": True}).json()
        sid = start(p, t["id"])
        with SessionLocal() as db:
            shutil.rmtree(db.get(TestSession, sid).folder)
        for step in ("trial1", "trial2"):
            listen.save_answer(sid, 5, step, {"phrases": [{"text": "face velvet"}], "final": {"text": "face velvet"},
                                              "end_reason": "x", "wav": f"{step}.wav"})
        self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/5/finish").status_code, 200)


class TestSharedEngine(unittest.TestCase):
    def test_lock_covers_only_the_transcribe_call(self):
        class Fake:
            supports_constrained = True

            def transcribe(self, *a, **k):
                self.locked = listen._engine_use_lock.locked()
                return {"text": "x"}

        fake = Fake()
        shared = listen.SharedEngine(fake)
        self.assertFalse(listen._engine_use_lock.locked())
        self.assertEqual(shared.transcribe("audio")["text"], "x")
        self.assertTrue(fake.locked)
        self.assertTrue(shared.supports_constrained)
        self.assertFalse(listen._engine_use_lock.locked())


class TestAdmin(unittest.TestCase):
    def test_only_admins_reach_the_portal(self):
        urls = ("/api/admin/stats", "/api/admin/users?role=patient")
        for who in (new_patient(), new_examiner()):
            for url in urls:
                self.assertEqual(who.get(url).status_code, 403)
            self.assertEqual(who.post("/api/admin/examiners", {"email": "a@b.co", "name": "X"}).status_code, 403)
            self.assertEqual(who.post(f"/api/admin/users/{who.id}/deactivate").status_code, 403)
        for url in urls:
            self.assertEqual(client.get(url).status_code, 401)

    def test_adding_an_examiner(self):
        a = new_admin()
        e = add_person(a, "examiner", title="Neurologist", organization="Lakeside")
        self.assertEqual(e.added.status_code, 200)
        self.assertEqual(e.get("/api/me").json()["role"], "examiner")
        self.assertEqual(e.get("/api/templates").json()[0]["name"], "Standard MoCA")
        self.assertIn(e.added.json()["id"], [u["id"] for u in a.get("/api/admin/users?role=examiner").json()])
        self.assertEqual(e.create.call_args.args[1], "Secret-123")      # signs in with this, no email

    def test_adding_a_patient(self):
        a = new_admin()
        p = add_person(a, "patient", education_years=9, date_of_birth="1950-01-01")
        self.assertEqual(p.get("/api/me").json()["profile"]["education_years"], 9)
        self.assertEqual(p.post("/api/me/onboard", {"name": "x"}).status_code, 409)

    def test_bad_details(self):
        a = new_admin()
        self.assertEqual(add_person(a, "patient", email="nope").added.status_code, 400)
        self.assertEqual(add_person(a, "examiner", name=" ").added.status_code, 400)
        self.assertEqual(add_person(a, "patient", education_years=99).added.status_code, 400)
        self.assertEqual(add_person(a, "examiner", password="short").added.status_code, 400)
        self.assertEqual(add_person(a, "examiner", password=None).added.status_code, 422)

    def test_an_email_cannot_be_used_twice(self):
        a = new_admin()
        first = add_person(a, "examiner")
        again = add_person(a, "patient", email=first.added.json()["email"].upper())
        self.assertEqual(again.added.status_code, 409)
        again.create.assert_not_called()

    def test_an_existing_login_is_never_adopted(self):
        """Someone registered the address first: they must not become an examiner."""
        a = new_admin()
        with mock.patch.object(supabase_admin, "create_login", side_effect=supabase_admin.EmailTaken("x")):
            r = a.post("/api/admin/examiners", {"email": "taken@example.com", "name": "Dr Real",
                                                "password": "Secret-123"})
        self.assertEqual(r.status_code, 409)

    def test_admin_cannot_see_any_test_results(self):
        a, e, p = new_admin(), new_examiner(), new_patient()
        sid = finished_test(p, e)
        e.post(f"/api/sessions/{sid}/release", {})
        self.assertEqual(a.get(f"/api/sessions/{sid}").status_code, 403)
        self.assertEqual(a.get("/api/sessions").status_code, 403)
        self.assertEqual(a.get("/api/patients").status_code, 403)
        self.assertEqual(a.get(f"/api/sessions/{sid}/files/x.wav").status_code, 403)
        row = next(u for u in a.get("/api/admin/users?role=patient").json() if u["id"] == p.id)
        self.assertEqual(set(row), {"id", "email", "role", "name", "active", "added_by_admin", "details", "tests"})

    def test_admins_cannot_touch_admins(self):
        a, other = new_admin(), new_admin()
        self.assertEqual(a.post(f"/api/admin/users/{other.id}/deactivate").status_code, 404)

    def test_deactivated_examiner_is_cut_off_and_hidden(self):
        a, e, p = new_admin(), new_examiner(), new_patient()
        sid = finished_test(p, e)
        self.assertEqual(a.post(f"/api/admin/users/{e.id}/deactivate").json()["active"], False)
        self.assertEqual(e.get(f"/api/sessions/{sid}").status_code, 403)
        self.assertEqual(e.get("/api/templates").status_code, 403)
        self.assertTrue(e.get("/api/me").json()["deactivated"])
        self.assertNotIn(e.standard["examiner_id"], [x["id"] for x in p.get("/api/examiners").json()])
        r = p.post("/api/sessions", {"template_id": e.standard["id"], "consent": True})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(p.get(f"/api/sessions/{sid}").status_code, 200)     # the patient keeps their history
        a.post(f"/api/admin/users/{e.id}/reactivate")
        self.assertEqual(e.get(f"/api/sessions/{sid}").status_code, 200)

    def test_deactivated_patient_is_cut_off_mid_test(self):
        a, e, p = new_admin(), new_examiner(), new_patient()
        sid = start(p, e.standard["id"])
        a.post(f"/api/admin/users/{p.id}/deactivate")
        self.assertEqual(p.post(f"/api/sessions/{sid}/tasks/1/skip").status_code, 403)
        with client.websocket_connect("/ws/listen") as ws:
            ws.send_json({"session_id": sid, "task": 4, "step": "lion", "token": token(p.id)})
            self.assertEqual(ws.receive_json()["type"], "error")

    def test_setting_a_new_password(self):
        a, p = new_admin(), new_patient()
        with mock.patch.object(supabase_admin, "set_password") as setp:
            self.assertEqual(a.post(f"/api/admin/users/{p.id}/password", {"password": "short"}).status_code, 400)
            self.assertEqual(a.post(f"/api/admin/users/{p.id}/password", {"password": "New-pass-99"}).status_code, 200)
            setp.assert_called_once_with(p.id, "New-pass-99")
            a.post(f"/api/admin/users/{p.id}/deactivate")
            self.assertEqual(a.post(f"/api/admin/users/{p.id}/password", {"password": "New-pass-99"}).status_code, 409)
        self.assertEqual(new_patient().post(f"/api/admin/users/{p.id}/password", {"password": "New-pass-99"}).status_code, 403)

    def test_stats(self):
        a = new_admin()
        before = a.get("/api/admin/stats").json()
        p = new_patient()
        a.post(f"/api/admin/users/{p.id}/deactivate")
        after = a.get("/api/admin/stats").json()
        self.assertEqual(after["deactivated"], before["deactivated"] + 1)
        self.assertEqual(after["patients"], before["patients"])


class TestPatientInvites(unittest.TestCase):
    DOB = "1948-03-02"

    def invite(self, examiner, email=None, dob=None):
        email = email or f"pat{_n[0]}@example.com"
        r = examiner.post("/api/invites", {"name": "Meena Rao", "email": email, "date_of_birth": dob or self.DOB})
        assert r.status_code == 200, r.text
        return r.json()

    def join(self, token, email, dob=None, education=8, user_id=None):
        """The patient opens the link. Supabase is replaced; returns (response, new login id)."""
        uid = user_id or Who().id
        with mock.patch.object(supabase_admin, "create_login", return_value=uid), \
                mock.patch.object(supabase_admin, "set_password") as setp:
            r = client.post(f"/api/join/{token}", json={"name": "Meena Rao", "email": email,
                                                        "date_of_birth": dob or self.DOB,
                                                        "education_years": education})
        return r, uid, setp

    def as_user(self, uid):
        w = Who.__new__(Who)
        w.id, w.headers = uid, {"Authorization": f"Bearer {token(uid)}"}
        return w

    def test_examiner_creates_a_link(self):
        e = new_examiner()
        inv = self.invite(e, "meena@example.com")
        self.assertGreaterEqual(len(inv["token"]), 40)
        self.assertIsNone(inv["joined_at"])
        self.assertEqual(self.invite(e, "MEENA@example.com")["token"], inv["token"])   # same patient, same link
        self.assertEqual([i["id"] for i in e.get("/api/invites").json()], [inv["id"]])

    def test_link_page_shows_only_the_examiner(self):
        e = new_examiner()
        inv = self.invite(e)
        info = client.get(f"/api/join/{inv['token']}").json()
        self.assertEqual(set(info), {"examiner", "joined"})
        self.assertNotIn(inv["email"], str(info))
        self.assertEqual(client.get("/api/join/not-a-real-token").status_code, 404)

    def test_details_must_match(self):
        e = new_examiner()
        inv = self.invite(e)
        self.assertEqual(self.join(inv["token"], "someone@else.com")[0].status_code, 400)
        self.assertEqual(self.join(inv["token"], inv["email"], dob="1960-01-01")[0].status_code, 400)
        self.assertEqual(self.join(inv["token"], inv["email"], education=None)[0].status_code, 400)

    def test_joining_creates_a_connected_patient(self):
        e, other = new_examiner(), new_examiner()
        inv = self.invite(e)
        r, uid, _ = self.join(inv["token"], inv["email"].upper())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["email"], inv["email"])
        self.assertGreaterEqual(len(r.json()["password"]), 24)
        p = self.as_user(uid)
        me = p.get("/api/me").json()
        self.assertEqual((me["role"], me["profile"]["education_years"]), ("patient", 8))
        # connected: the patient sees only this examiner, and the examiner sees the patient
        self.assertEqual([x["id"] for x in p.get("/api/examiners").json()], [e.standard["examiner_id"]])
        self.assertIn(me["profile"]["id"], [x["id"] for x in e.get("/api/patients").json()])
        self.assertEqual(e.get(f"/api/patients/{me['profile']['id']}").status_code, 200)
        self.assertEqual(other.get(f"/api/patients/{me['profile']['id']}").status_code, 404)
        self.assertEqual(p.post("/api/sessions", {"template_id": other.standard["id"], "consent": True}).status_code, 404)
        self.assertEqual(p.post("/api/sessions", {"template_id": e.standard["id"], "consent": True}).status_code, 200)
        self.assertIsNotNone(e.get("/api/invites").json()[0]["joined_at"])

    def test_opening_the_link_again_signs_them_back_in(self):
        e = new_examiner()
        inv = self.invite(e)
        _, uid, _ = self.join(inv["token"], inv["email"])
        r, _, setp = self.join(inv["token"], inv["email"], education=12)
        self.assertEqual(r.status_code, 200)
        setp.assert_called_once()
        self.assertEqual(setp.call_args.args, (uid, r.json()["password"]))
        self.assertEqual(self.as_user(uid).get("/api/me").json()["profile"]["education_years"], 12)

    def test_own_account_is_connected_but_password_untouched(self):
        e, p = new_examiner(), new_patient()
        email = f"{p.id}@example.com"
        with SessionLocal() as db:
            db.get(User, p.id).email = email
            db.commit()
        inv = self.invite(e, email, dob="1950-02-03")
        r, _, setp = self.join(inv["token"], email, dob="1950-02-03")
        self.assertEqual(r.json(), {"sign_in": True, "email": email})
        setp.assert_not_called()
        self.assertIn(e.standard["examiner_id"], [x["id"] for x in p.get("/api/examiners").json()])
        r, _, setp = self.join(inv["token"], email, dob="1950-02-03")
        self.assertTrue(r.json()["sign_in"])
        setp.assert_not_called()

    def test_staff_email_cannot_join(self):
        e = new_examiner()
        staff = new_examiner()
        email = staff.added.json()["email"]
        inv = self.invite(e, email)
        self.assertEqual(self.join(inv["token"], email)[0].status_code, 409)

    def test_only_examiners_make_or_delete_links(self):
        e, p = new_examiner(), new_patient()
        self.assertEqual(p.post("/api/invites", {"name": "x", "email": "x@y.co", "date_of_birth": self.DOB}).status_code, 403)
        inv = self.invite(e)
        self.assertEqual(new_examiner().delete(f"/api/invites/{inv['id']}").status_code, 404)
        self.assertEqual(e.delete(f"/api/invites/{inv['id']}").status_code, 200)
        self.assertEqual(client.get(f"/api/join/{inv['token']}").status_code, 404)

    def test_bad_invite_details(self):
        e = new_examiner()
        for body in ({"name": "", "email": "a@b.co", "date_of_birth": self.DOB},
                     {"name": "A", "email": "nope", "date_of_birth": self.DOB},
                     {"name": "A", "email": "a@b.co", "date_of_birth": "2999-01-01"}):
            self.assertEqual(e.post("/api/invites", body).status_code, 400, body)

    def test_deactivated_examiners_links_stop_working(self):
        a, e = new_admin(), new_examiner()
        inv = self.invite(e)
        a.post(f"/api/admin/users/{e.id}/deactivate")
        self.assertEqual(client.get(f"/api/join/{inv['token']}").status_code, 404)


class TestServing(unittest.TestCase):
    def test_security_headers(self):
        h = client.get("/api/status").headers
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["cache-control"], "no-store")

    def test_public_config_holds_no_secrets(self):
        cfg = client.get("/api/public-config").json()
        self.assertEqual(set(cfg), {"supabase_url", "supabase_anon_key", "google_login"})
        self.assertNotIn(SECRET, str(cfg))

    def test_unknown_api_path_is_not_the_page(self):
        self.assertEqual(client.get("/api/nope").status_code, 404)

    def test_page_routes_cannot_escape_the_build_folder(self):
        r = client.get("/..%2F..%2Fmoca_common.py")
        self.assertNotIn("make_task_result", r.text)


if __name__ == "__main__":
    unittest.main()
