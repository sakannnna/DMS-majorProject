"""Real MongoDB integration tests. All test databases are generated and isolated."""
import os
import uuid
import hashlib
import json
import subprocess
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from bson import Decimal128, ObjectId
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import WriteError

from app.database import initialize, now, public
from app.logic import normalize, prepare_survey, walk
from app.main import create_app
from app.models import Answer, SurveyInput

PASSWORD = "course-test-password"


class Browser:
    def __init__(self, app):
        self.client = TestClient(app)
        self.client.headers["x-csrf-token"] = self.client.get("/api/session").json()["csrf"]

    def request(self, method, path, body=None):
        return self.client.request(method, path, json=body) if body is not None else self.client.request(method, path)

    def account(self, name):
        assert self.request("POST", "/api/register", {"username": name, "password": PASSWORD}).status_code == 201
        assert self.request("POST", "/api/login", {"username": name, "password": PASSWORD}).status_code == 200
        return self


@pytest.fixture
def env():
    client = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27019"), tz_aware=True, serverSelectionTimeoutMS=3000)
    name = "survey_course_test_" + uuid.uuid4().hex
    db = client[name]
    app = create_app(db)
    owner = None
    try:
        with TestClient(app):
            owner = Browser(app).account("owner")
            yield db, app, owner
    finally:
        # Also clean this exact generated database when startup/setup fails before yield.
        if owner is not None:
            owner.client.close()
        assert name.startswith("survey_course_test_") and len(name) == len("survey_course_test_") + 32
        client.drop_database(name)
        client.close()


def question(kind="single", id="q1", **extra):
    q = {"id": id, "kind": kind, "title": id, "required": True}
    if kind in ("single", "multiple"):
        q["options"] = [{"id": x, "label": x.upper()} for x in "abc"]
    return {**q, **extra}


def create(owner, questions=None, **extra):
    body = {"title": "测试问卷", "questions": questions if questions is not None else [question()], **extra}
    r = owner.request("POST", "/api/surveys", body)
    assert r.status_code == 201, r.text
    return r.json()


def publish(owner, s):
    r = owner.request("POST", f"/api/surveys/{s['id']}/publish", {"editRevision": s["editRevision"]})
    assert r.status_code == 200, r.text
    return r.json()


def payload(answers=None, **extra):
    return {"answers": answers if answers is not None else [{"questionId": "q1", "value": "a"}], "submissionKey": uuid.uuid4().hex, **extra}


def test_T01_account_permissions_csrf_session(env):
    db, app, owner = env
    assert {"users", "surveys", "responses", "sessions"} <= set(db.list_collection_names())
    guest = Browser(app)
    assert guest.request("GET", "/api/surveys").status_code == 401
    assert guest.client.post("/api/login", json={"username": "owner", "password": PASSWORD}, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert guest.request("POST", "/api/register", {"username": "OWNER", "password": PASSWORD}).status_code == 409
    assert guest.request("POST", "/api/login", {"username": "owner", "password": "wrong-password"}).status_code == 401
    stored = db.users.find_one({"usernameKey": "owner"})
    assert stored["passwordHash"].startswith("$argon2") and PASSWORD not in stored["passwordHash"]
    s = create(owner)
    other = Browser(app).account("other")
    assert other.request("GET", "/api/surveys").json() == []
    for method, path, body in [("GET", "", None), ("GET", "/stats", None),
                               ("PATCH", "/metadata", {"title": "hack", "editRevision": 1}),
                               ("POST", "/publish", {"editRevision": 1}), ("POST", "/close", {"editRevision": 1}),
                               ("POST", "/preview", {"answers": []})]:
        assert other.request(method, f"/api/surveys/{s['id']}{path}", body).status_code == 404
    assert owner.request("POST", "/api/logout", {}).status_code == 200
    assert owner.request("GET", "/api/surveys").status_code == 401
    assert other.request("POST", "/api/logout", {}).status_code == 200
    assert not db.sessions.count_documents({})


def test_T02_lifecycle_frozen_settings_and_metadata(env):
    db, app, owner = env
    s = create(owner)
    stored = db.surveys.find_one({"_id": ObjectId(s["id"])})
    assert stored["title"] == "测试问卷" and stored["status"] == "draft"
    assert stored["ownerId"] == db.users.find_one({"usernameKey": "owner"})["_id"]
    assert stored["token"] == s["token"] and db.responses.count_documents({}) == 0
    assert Browser(app).request("GET", f"/api/fill/{s['token']}").status_code == 401
    assert owner.request("GET", f"/api/fill/{s['token']}").status_code == 409
    s = publish(owner, s)
    assert owner.request("PUT", f"/api/surveys/{s['id']}", {"title": "改题", "editRevision": s["editRevision"]}).status_code == 409
    assert owner.request("PATCH", f"/api/surveys/{s['id']}/metadata", {"title": "更名", "editRevision": s["editRevision"], "allowMultiple": True}).status_code == 422
    stale = s["editRevision"]
    s = owner.request("PATCH", f"/api/surveys/{s['id']}/metadata", {"title": "更名", "description": "新说明", "editRevision": stale, "deadline": (now() - timedelta(seconds=5)).isoformat()}).json()
    assert s["title"] == "更名" and s["description"] == "新说明"
    assert s["definitionVersion"] == 1 and s["questions"][0]["id"] == "q1"
    assert owner.request("PATCH", f"/api/surveys/{s['id']}/metadata", {"title": "旧写入", "editRevision": stale}).status_code == 409
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload()).status_code == 409
    s = owner.request("PATCH", f"/api/surveys/{s['id']}/metadata", {"title": s["title"], "editRevision": s["editRevision"], "deadline": (now() + timedelta(days=1)).isoformat()}).json()
    assert owner.request("GET", f"/api/fill/{s['token']}").status_code == 200
    s = owner.request("POST", f"/api/surveys/{s['id']}/close", {"editRevision": s["editRevision"]}).json()
    s = owner.request("PATCH", f"/api/surveys/{s['id']}/metadata", {"title": s["title"], "editRevision": s["editRevision"], "deadline": None}).json()
    assert s["status"] == "closed"
    assert owner.request("POST", f"/api/surveys/{s['id']}/publish", {"editRevision": s["editRevision"]}).status_code == 409
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload()).status_code == 409
    assert db.responses.count_documents({}) == 0


def test_T03_add_edit_questions_preview_and_concurrency(env):
    db, _, owner = env
    s = create(owner, [])
    assert owner.request("POST", f"/api/surveys/{s['id']}/publish", {"editRevision": 1}).status_code == 422
    edited = {"title": "四种输入", "questions": [question(), question("multiple", "q2"), question("text", "q3"), question("number", "q4")], "editRevision": 1}
    r = owner.request("PUT", f"/api/surveys/{s['id']}", edited)
    assert r.status_code == 200
    assert len(r.json()["questions"]) == 4
    stored = db.surveys.find_one({"_id": ObjectId(s["id"])})
    assert [(q["id"], q["kind"], q["required"]) for q in stored["questions"]] == [
        ("q1", "single", True), ("q2", "multiple", True), ("q3", "text", True), ("q4", "number", True)]
    assert [[o["id"] for o in q["options"]] for q in stored["questions"]] == [["a", "b", "c"], ["a", "b", "c"], [], []]
    assert owner.request("PUT", f"/api/surveys/{s['id']}", edited).status_code == 409
    p = owner.request("POST", f"/api/surveys/{s['id']}/preview", {"answers": [{"questionId": "q1", "value": "a"}]})
    assert p.status_code == 200 and p.json()["walk"]["nextQuestionId"] == "q2"
    assert db.responses.count_documents({}) == 0


@pytest.mark.parametrize("questions", [
    [question(), question(id="q1")],
    [question(id="END")],
    [question(options=[{"id": "a", "label": "唯一"}])],
    [question(jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "q1"}])],
    [question(jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "missing"}])],
    [question(), question(id="q2", jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "q1"}])],
    [question(validation={"minChoices": 0})],
    [question("multiple", validation={"minChoices": 4})],
    [question("text", jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "END"}])],
    [question("number", validation={"minimum": "5", "maximum": "2"})],
])
def test_T04_invalid_definition(questions):
    with pytest.raises(HTTPException):
        prepare_survey(SurveyInput(title="测试", questions=questions))


@pytest.mark.parametrize("kind,validation,value,valid", [
    ("single", {}, "a", True), ("single", {}, "bad", False), ("single", {}, None, False),
    ("multiple", {"minChoices": 2, "maxChoices": 2}, ["a", "b"], True),
    ("multiple", {"minChoices": 2, "maxChoices": 2}, ["a"], False),
    ("multiple", {"minChoices": 2, "maxChoices": 2}, ["a", "b", "c"], False),
    ("multiple", {}, ["a", "a"], False), ("multiple", {}, ["bad"], False),
    ("text", {"minLength": 2, "maxLength": 3}, "  中文  ", True),
    ("text", {"minLength": 2, "maxLength": 3}, "字", False),
    ("text", {"maxLength": 3}, "四个汉字", False),
    ("number", {"minimum": "0", "maximum": "120", "integer": True}, "0", True),
    ("number", {"minimum": "0", "maximum": "120", "integer": True}, "120", True),
    ("number", {"minimum": "0", "maximum": "120", "integer": True}, "121", False),
    ("number", {"minimum": "0", "maximum": "120", "integer": True}, "-1", False),
    ("number", {"integer": True}, "1.5", False), ("number", {}, "NaN", False),
    ("number", {}, "Infinity", False), ("number", {}, "abc", False),
    ("number", {}, "1e9999", False),
])
def test_T05_validation(kind, validation, value, valid):
    s = prepare_survey(SurveyInput(title="测试", questions=[question(kind, validation=validation)]))
    if valid:
        expected = {("single", "a"): "a", ("multiple", "a,b"): ["a", "b"],
                    ("text", "  中文  "): "中文", ("number", "0"): Decimal128("0"),
                    ("number", "120"): Decimal128("120")}
        result = normalize(s["questions"][0], value)
        assert result == expected[(kind, ",".join(value) if isinstance(value, list) else value)]
        if kind == "number":
            assert isinstance(result, Decimal128)
    else:
        with pytest.raises(HTTPException):
            normalize(s["questions"][0], value)


@pytest.mark.parametrize("kind,value,conditions", [
    ("single", "a", [{"op": "eq", "value": "a"}]),
    ("multiple", ["a", "b"], [{"op": "all", "value": ["a", "b"]}]),
    ("multiple", ["a"], [{"op": "any", "value": ["a", "b"]}]),
    ("number", "20", [{"op": "gte", "value": "18"}, {"op": "lt", "value": "30"}]),
])
def test_T06_jump_first_match_end_and_unmatched(kind, value, conditions):
    qs = [question(kind, jumpRules=[{"conditions": conditions, "target": "q3"}, {"conditions": conditions, "target": "END"}]),
          question("text", "q2"), question("text", "q3", required=False)]
    s = prepare_survey(SurveyInput(title="测试", questions=qs))
    result, _ = walk(s, [Answer(questionId="q1", value=value)])
    assert result == {"path": ["q1", "q3"], "nextQuestionId": "q3", "ready": False}
    qs[0]["jumpRules"][0]["target"] = "END"
    s = prepare_survey(SurveyInput(title="测试", questions=qs))
    assert walk(s, [Answer(questionId="q1", value=value)])[0]["ready"] is True
    other = "b" if kind == "single" else ["c"] if kind == "multiple" else "10"
    assert walk(s, [Answer(questionId="q1", value=other)])[0]["nextQuestionId"] == "q2"
    with pytest.raises(HTTPException):
        walk(s, [Answer(questionId="q1", value=value), Answer(questionId="q2", value="残留答案")], complete=True)


def test_T07_end_confirmation_does_not_submit(env):
    db, _, owner = env
    s = publish(owner, create(owner, [question(jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "END"}]), question("text", "q2")]))
    body = payload()
    r = owner.request("POST", f"/api/fill/{s['token']}/walk", {"answers": body["answers"]})
    assert r.json()["ready"] is True and r.json()["path"] == ["q1"]
    assert db.responses.count_documents({}) == 0
    owner.request("POST", f"/api/surveys/{s['id']}/close", {"editRevision": s["editRevision"]})
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", body).status_code == 409
    assert db.responses.count_documents({}) == 0


def test_T08_submission_retry_anonymity_and_statistics(env):
    db, app, owner = env
    qs = [question(), question("multiple", "q2"), question("text", "q3", required=False), question("number", "q4")]
    s = publish(owner, create(owner, qs, allowMultiple=True))
    visitor = Browser(app).account("visitor")
    for index, (choice, options, text, num, anon) in enumerate([
        ("a", ["a", "b"], "你好", "0.1", True), ("b", ["b"], None, "0.2", False), ("a", ["a"], "第三份", "0.3", True)]):
        answers = [{"questionId": "q1", "value": choice}, {"questionId": "q2", "value": options},
                   {"questionId": "q3", "value": text}, {"questionId": "q4", "value": num}]
        body = payload(answers, anonymous=anon)
        r = visitor.request("POST", f"/api/fill/{s['token']}/submit", body)
        assert r.status_code == 200, r.text
        saved = db.responses.find_one({"_id": ObjectId(r.json()["responseId"])})
        expected_answers = [{"questionId": "q1", "value": choice}, {"questionId": "q2", "value": sorted(options)}]
        if text is not None:
            expected_answers.append({"questionId": "q3", "value": text})
        expected_answers.append({"questionId": "q4", "value": Decimal128(num)})
        assert saved["answers"] == expected_answers
        assert saved["anonymous"] is anon
        assert saved["respondentId"] == db.users.find_one({"usernameKey": "visitor"})["_id"]
        replay = visitor.request("POST", f"/api/fill/{s['token']}/submit", body)
        assert replay.json()["replayed"] is True
        body["anonymous"] = not anon
        assert visitor.request("POST", f"/api/fill/{s['token']}/submit", body).status_code == 409
    assert db.responses.count_documents({}) == 3
    assert all(isinstance(r["answers"][-1]["value"], Decimal128) for r in db.responses.find({}))
    stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    assert stats["total"] == 3
    assert stats["respondentCount"] == 1
    assert all(q["respondentCount"] == 1 for q in stats["questions"])
    a, b, c, d = stats["questions"]
    assert [o["count"] for o in a["options"]] == [2, 1, 0]
    assert [o["count"] for o in b["options"]] == [2, 2, 0]
    assert [o["respondentCount"] for o in a["options"]] == [1, 1, 0]
    assert [o["respondentCount"] for o in b["options"]] == [1, 1, 0]
    assert c["answered"] == 2 and d["average"] == "0.2"
    assert {r["author"] for r in c["contents"]} == {"匿名"}
    assert {r["author"] for r in d["contents"]} == {"匿名", "visitor"}
    encoded = str(stats)
    assert "respondentId" not in encoded and "singleSubmissionKey" not in encoded and "payloadHash" not in encoded
    one = owner.request("GET", f"/api/surveys/{s['id']}/questions/q3/stats?skip=0&limit=1").json()
    assert len(one["contents"]) == 1 and one["hasMore"]
    assert visitor.request("GET", f"/api/surveys/{s['id']}/stats").status_code == 404


def test_T09_concurrent_one_user_and_multiple_users(env):
    db, app, owner = env
    s = publish(owner, create(owner))
    readers = [Browser(app).account(f"reader{x}") for x in range(4)]
    # Each request uses its own HTTP client; same credentials/cookies model concurrent browser tabs.
    # Plain clients share the already-started app without rerunning its lifespan.
    def send(pair):
        source, body = pair
        client = TestClient(app)
        try:
            client.cookies.update(source.client.cookies)
            client.headers["x-csrf-token"] = source.client.headers["x-csrf-token"]
            return client.post(f"/api/fill/{s['token']}/submit", json=body).status_code
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, [(readers[0], payload()) for _ in range(8)]))
    assert results.count(200) == 1 and results.count(409) == 7
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(send, [(r, payload()) for r in readers[1:]])) == [200, 200, 200]
    assert db.responses.count_documents({}) == 4


def test_T10_empty_stats_no_anonymous_and_schema(env):
    db, app, owner = env
    s = publish(owner, create(owner, [question("number")], allowAnonymous=False))
    data = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    assert data["total"] == 0 and data["questions"][0]["average"] is None
    assert data["respondentCount"] == data["questions"][0]["respondentCount"] == 0
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload([{ "questionId": "q1", "value": "0"}], anonymous=True)).status_code == 200
    assert db.responses.find_one({})["anonymous"] is False
    with pytest.raises(WriteError):
        db.responses.insert_one({"surveyId": ObjectId(), "answers": []})
    assert owner.request("POST", "/api/surveys", {"title": "  "}).status_code == 422


def test_T11_unknown_duplicate_and_missing_answers(env):
    db, _, owner = env
    s = publish(owner, create(owner))
    for answers in [[], [{"questionId": "missing", "value": "a"}], [{"questionId": "q1", "value": "a"}] * 2,
                    [{"questionId": "q1", "value": "bad"}]]:
        assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload(answers)).status_code == 422
    assert db.responses.count_documents({}) == 0


def test_T12_optional_empty_and_zero():
    s = prepare_survey(SurveyInput(title="选填", questions=[question("number", required=False, validation={"minimum": "0"})]))
    q = s["questions"][0]
    assert normalize(q, None) is None
    assert normalize(q, "0").to_decimal() == 0
    assert walk(s, [Answer(questionId="q1", value=None)], complete=True)[0]["ready"]


def test_T15_restart_preserves_data_and_indexes(env):
    db, _, owner = env
    s = publish(owner, create(owner))
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload()).status_code == 200
    initialize(db)
    assert db.responses.count_documents({}) == 1
    assert owner.request("GET", f"/api/surveys/{s['id']}/stats").json()["total"] == 1
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload()).status_code == 409


def test_T16_expired_session_origin_and_request_size(env):
    db, _, owner = env
    assert owner.client.post("/api/surveys", json={"title": "attack"}, headers={"origin": "https://other.invalid"}).status_code == 403
    assert owner.request("POST", "/api/surveys", {"title": "large", "description": "x" * 2_500_001}).status_code == 413
    db.sessions.update_many({}, {"$set": {"expiresAt": now() - timedelta(hours=1)}})
    assert owner.request("GET", "/api/surveys").status_code == 401


def test_T17_concurrent_same_key_retry(env):
    db, app, owner = env
    s = publish(owner, create(owner, allowMultiple=True))
    body = payload()
    def send(_):
        client = TestClient(app)
        try:
            client.cookies.update(owner.client.cookies)
            client.headers["x-csrf-token"] = owner.client.headers["x-csrf-token"]
            r = client.post(f"/api/fill/{s['token']}/submit", json=body)
            assert r.status_code == 200
            return r.json()
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(8)))
    assert len({r["responseId"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1
    assert db.responses.count_documents({}) == 1


def test_T18_skipped_required_question_and_stats(env):
    db, _, owner = env
    s = publish(owner, create(owner, [question(jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "END"}]), question("number", "q2")]))
    assert owner.request("POST", f"/api/fill/{s['token']}/submit", payload()).status_code == 200
    stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    assert stats["total"] == 1
    assert stats["questions"][0]["answered"] == 1
    assert stats["questions"][1]["answered"] == 0 and stats["questions"][1]["average"] is None
    assert stats["respondentCount"] == stats["questions"][0]["respondentCount"] == 1
    assert stats["questions"][1]["respondentCount"] == 0


def test_T19_response_contracts_and_frontend_fields(env):
    from pydantic import TypeAdapter, ValidationError
    from app.contracts import QuestionStatsOut
    db, app, owner = env
    spec = app.openapi()
    operations = [operation for path, methods in spec["paths"].items() if path.startswith("/api/")
                  for operation in methods.values()]
    assert {"/api/session", "/api/surveys", "/api/fill/{token}/submit"} <= spec["paths"].keys()
    assert operations
    for operation in operations:
        for code, response in operation["responses"].items():
            if code.startswith("2") or code in ("401", "403", "404", "409", "413", "422"):
                assert response["content"]["application/json"]["schema"]
    s = create(owner, [question(), question("multiple", "q2"), question("text", "q3"), question("number", "q4")])
    db.surveys.update_one({"_id": ObjectId(s["id"])}, {"$set": {"futureInternalField": "private"}})
    detail = owner.request("GET", f"/api/surveys/{s['id']}").json()
    assert "futureInternalField" not in detail
    assert {"id", "status", "editRevision", "token", "questions", "deadline"} <= detail.keys()
    summary = owner.request("GET", "/api/surveys").json()[0]
    assert "questions" not in summary and "futureInternalField" not in summary
    preview = owner.request("POST", f"/api/surveys/{s['id']}/preview", {"answers": []}).json()
    assert set(preview) == {"survey", "walk"}
    assert preview["walk"] == {"path": ["q1"], "nextQuestionId": "q1", "ready": False}
    assert "deadline" not in preview["survey"]  # Frontend must not assume fill and preview are identical.
    s = publish(owner, s)
    fill = owner.request("GET", f"/api/fill/{s['token']}").json()
    assert {"deadline", "definitionVersion", "questions", "allowAnonymous"} <= fill.keys()
    assert not {"ownerId", "token", "editRevision"} & fill.keys()
    stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    adapter = TypeAdapter(QuestionStatsOut)
    for item in stats["questions"]:
        adapter.validate_python(item)
        if item["kind"] in ("single", "multiple"):
            assert "options" in item and "contents" not in item
        else:
            assert {"contents", "skip", "limit", "hasMore"} <= item.keys() and "options" not in item
    assert stats["questions"][-1]["average"] is None
    assert stats["respondentCount"] == 0
    for item in stats["questions"]:
        broken_count = dict(item)
        broken_count.pop("respondentCount")
        with pytest.raises(ValidationError):
            adapter.validate_python(broken_count)
    broken = dict(stats["questions"][-1]); broken.pop("average")
    with pytest.raises(ValidationError):
        adapter.validate_python(broken)


@pytest.mark.parametrize("with_document", [False, True])
def test_T20_old_initializer_does_not_overwrite_future_schema(env, with_document):
    import copy
    import types
    db, _, owner = env
    s = create(owner)
    legacy = types.ModuleType("stage1_database")
    exec(subprocess.check_output(["git", "show", "stage1-final:app/database.py"]).decode("utf-8"), legacy.__dict__)
    if not with_document:
        db.surveys.update_one({"_id": ObjectId(s["id"])}, {"$set": {"schemaVersion": 1}})
    validator = copy.deepcopy(db.surveys.options()["validator"])
    validator["$jsonSchema"]["properties"]["schemaVersion"]["enum"] = [1, 2]
    db.command("collMod", "surveys", validator=validator)
    if with_document:
        db.surveys.update_one({"_id": ObjectId(s["id"])}, {"$set": {"schemaVersion": 2}})
    before = {name: db[name].options() for name in db.list_collection_names()}
    with pytest.raises(RuntimeError, match="Unsupported schema"):
        legacy.initialize(db)
    assert before == {name: db[name].options() for name in db.list_collection_names()}
    assert db.surveys.count_documents({}) == 1


def test_T22_statistics_pages_no_duplicates_or_omissions(env):
    from datetime import datetime, timezone
    db, _, owner = env
    s = publish(owner, create(owner, [question("text", "q1"), question("number", "q2")], allowMultiple=True))
    ids = []
    for i in range(23):
        body = payload([{"questionId": "q1", "value": f"内容{i:02d}"}, {"questionId": "q2", "value": str(i)}])
        r = owner.request("POST", f"/api/fill/{s['token']}/submit", body)
        assert r.status_code == 200
        ids.append(ObjectId(r.json()["responseId"]))
    assert ids == sorted(ids)  # Declared fixture ordering, not the pagination response as oracle.
    db.responses.update_many({"surveyId": ObjectId(s["id"])}, {"$set": {"submittedAt": datetime(2026, 10, 17, tzinfo=timezone.utc)}})
    for qid in ("q1", "q2"):
        actual = []
        for skip, size, more in [(0, 7, True), (7, 7, True), (14, 7, True), (21, 2, False), (28, 0, False)]:
            r = owner.request("GET", f"/api/surveys/{s['id']}/questions/{qid}/stats?skip={skip}&limit=7")
            assert r.status_code == 200
            page = r.json()
            assert len(page["contents"]) == size and page["hasMore"] is more and page["answered"] == 23
            actual.extend(row["value"] for row in page["contents"])
            if qid == "q2":
                assert page["average"] == "11"
        expected = [f"内容{i:02d}" if qid == "q1" else str(i) for i in range(22, -1, -1)]
        assert actual == expected and len(set(actual)) == 23
    whole = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    for q in whole["questions"]:
        first = owner.request("GET", f"/api/surveys/{s['id']}/questions/{q['questionId']}/stats?limit=20").json()
        assert q == first


@contextmanager
def measured_case(name, db):
    """Write bounded evidence even when a request or an assertion fails."""
    started = time.perf_counter()
    report = {"case": name, "database": db.name, "passed": False, "requestFailures": [],
              "baseCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "testSourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "timingScope": "test body; excludes env fixture setup and cleanup; seconds"}
    try:
        yield report
        report["passed"] = True
    except BaseException as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["elapsedSeconds"] = round(time.perf_counter() - started, 3)
        prefix = os.getenv("SURVEY_TEST_EVIDENCE_PREFIX", "stage2-part2-")
        if not all(c.isalnum() or c in "_-" for c in prefix):
            raise ValueError("Invalid evidence prefix")
        target = Path(__file__).resolve().parents[1] / "docs" / "evidence" / f"{prefix}{name}.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def test_T23_complete_flow_smoke(env):
    db, app, owner = env
    with measured_case("T23-smoke", db) as evidence:
        assert owner.client.get("/").status_code == 200
        assert owner.client.get("/static/app.js").status_code == 200
        s = publish(owner, create(owner, [
            question(jumpRules=[{"conditions": [{"op": "eq", "value": "a"}], "target": "END"}]),
            question("multiple", "q2"), question("text", "q3"), question("number", "q4")]))
        reader = Browser(app).account("smoke_reader")
        try:
            assert reader.request("GET", f"/api/fill/{s['token']}").status_code == 200
            answers = [{"questionId": "q1", "value": "b"}, {"questionId": "q2", "value": ["a", "b"]},
                       {"questionId": "q3", "value": "  冒烟回答  "}, {"questionId": "q4", "value": "12"}]
            for n, next_id in [(1, "q2"), (2, "q3"), (3, "q4"), (4, None)]:
                r = reader.request("POST", f"/api/fill/{s['token']}/walk", {"answers": answers[:n]})
                assert r.status_code == 200
                assert r.json()["nextQuestionId"] == next_id and r.json()["ready"] is (n == 4)
            assert db.responses.count_documents({}) == 0
            body = payload(answers, anonymous=False)
            first = reader.request("POST", f"/api/fill/{s['token']}/submit", body)
            retry = reader.request("POST", f"/api/fill/{s['token']}/submit", body)
            assert first.status_code == retry.status_code == 200
            assert first.json()["responseId"] == retry.json()["responseId"] and retry.json()["replayed"]
            assert db.responses.count_documents({}) == 1
            assert db.responses.find_one({})["answers"] == [answers[0], answers[1],
                {"questionId": "q3", "value": "冒烟回答"}, {"questionId": "q4", "value": Decimal128("12")}]
            r = owner.request("GET", f"/api/surveys/{s['id']}/stats")
            assert r.status_code == 200
            stats = r.json()
            assert stats["total"] == 1
            assert [o["count"] for o in stats["questions"][0]["options"]] == [0, 1, 0]
            assert [o["count"] for o in stats["questions"][1]["options"]] == [1, 1, 0]
            assert stats["questions"][2]["contents"][0]["value"] == "冒烟回答"
            assert stats["questions"][3]["average"] == "12"
            assert owner.request("POST", f"/api/surveys/{s['id']}/close", {"editRevision": s["editRevision"]}).status_code == 200
            assert reader.request("POST", f"/api/fill/{s['token']}/submit", payload(answers)).status_code == 409
            assert db.responses.count_documents({}) == 1
            evidence.update({"storedResponses": 1, "sameKeyReplayAdded": 0, "closedSubmitStatus": 409})
        finally:
            reader.client.close()


def test_T24_hundred_accounts_submission_correctness(env):
    db, app, owner = env
    clients = []
    try:
        with measured_case("T24-correctness", db) as evidence:
            preparation = time.perf_counter()
            s = publish(owner, create(owner, [question(), question("multiple", "q2"),
                question("text", "q3"), question("number", "q4")]))
            expected = {}
            for i in range(100):
                name = f"batch{i:03d}"
                browser = Browser(app).account(name)
                clients.append(browser)
                answers = [{"questionId": "q1", "value": "a" if i % 2 == 0 else "b"},
                           {"questionId": "q2", "value": [["a"], ["b"], ["a", "b"], ["b", "c"]][i % 4]},
                           {"questionId": "q3", "value": f"account-{i:03d}"},
                           {"questionId": "q4", "value": str(i)}]
                expected[name] = answers
            evidence["preparationSeconds"] = round(time.perf_counter() - preparation, 3)
            active, peak = 0, 0
            lock = threading.Lock()
            def send(i):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                result = {"account": f"batch{i:03d}"}
                try:
                    body = payload(expected[result["account"]], anonymous=False)
                    for stage in ("first", "retry"):
                        r = clients[i].request("POST", f"/api/fill/{s['token']}/submit", body)
                        result[stage] = {"status": r.status_code, "body": r.json()}
                except Exception as exc:
                    result["exception"] = f"{type(exc).__name__}: {exc}"
                finally:
                    with lock:
                        active -= 1
                return result
            workload = time.perf_counter()
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(send, range(100)))
            evidence.update({"submitAndRetrySeconds": round(time.perf_counter() - workload, 3),
                "accounts": 100, "workerLimit": 10, "observedPeakActiveWorkers": peak,
                "requestFailures": [r for r in results if "exception" in r or
                    any(r.get(k, {}).get("status") != 200 for k in ("first", "retry"))]})
            assert not evidence["requestFailures"], evidence["requestFailures"]
            assert all(not r["first"]["body"]["replayed"] and r["retry"]["body"]["replayed"] and
                       r["first"]["body"]["responseId"] == r["retry"]["body"]["responseId"] for r in results)
            rows = list(db.responses.find({"surveyId": ObjectId(s["id"])}))
            users = {u["username"]: u["_id"] for u in db.users.find({"username": {"$in": list(expected)}})}
            assert len(rows) == len(users) == 100
            assert {r["respondentId"] for r in rows} == set(users.values())
            by_user = {r["respondentId"]: r for r in rows}
            for name, inputs in expected.items():
                stored = by_user[users[name]]
                assert stored["answers"] == inputs[:3] + [{"questionId": "q4", "value": Decimal128(inputs[3]["value"])}]
                assert stored["anonymous"] is False and stored["singleSubmissionKey"] == users[name]
            stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
            assert stats["total"] == 100
            assert all(q["answered"] == 100 for q in stats["questions"])
            assert stats["respondentCount"] == 100
            assert all(q["respondentCount"] == 100 for q in stats["questions"])
            for q in stats["questions"][:2]:
                assert all(o["respondentCount"] == o["count"] for o in q["options"])
            assert [o["count"] for o in stats["questions"][0]["options"]] == [50, 50, 0]
            assert [o["count"] for o in stats["questions"][1]["options"]] == [50, 75, 25]
            assert stats["questions"][3]["average"] == "49.5"
            for qid, column in [("q3", 2), ("q4", 3)]:
                r = owner.request("GET", f"/api/surveys/{s['id']}/questions/{qid}/stats?limit=100")
                assert r.status_code == 200
                content = r.json()
                assert len(content["contents"]) == 100 and not content["hasMore"]
                assert {row["author"]: row["value"] for row in content["contents"]} == {
                    name: answers[column]["value"] for name, answers in expected.items()}
            evidence.update({"firstSuccessful": 100, "retrySuccessful": 100, "storedResponses": 100,
                "uniqueRespondents": 100, "sameKeyReplayAdded": 0, "accountAnswerMapping": "exact match",
                "statistics": {"single": [50, 50, 0], "multiple": [50, 75, 25], "average": "49.5"}})
    finally:
        for browser in clients:
            browser.client.close()


@pytest.mark.parametrize("field", ["minimum", "maximum"])
@pytest.mark.parametrize("value", ["1e6145", "1e-6177", "1.2345678901234567890123456789012345"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_T26_config_bounds_reject_without_writes(env, field, value, operation):
    db, app, owner = env
    s = create(owner, [question("number")])
    before = db.surveys.find_one({"_id": ObjectId(s["id"])})
    body = {"title": "invalid bounds", "questions": [question("number", validation={field: value})]}
    path, method = "/api/surveys", "POST"
    if operation == "update":
        path, method = f"/api/surveys/{s['id']}", "PUT"
        body["editRevision"] = s["editRevision"]
    client = TestClient(app, raise_server_exceptions=False)
    try:
        client.cookies.update(owner.client.cookies)
        client.headers["x-csrf-token"] = owner.client.headers["x-csrf-token"]
        r = client.request(method, path, json=body)
        assert r.status_code == 422, f"{field}={value} returned {r.status_code}"
        assert "Decimal128" in r.json()["detail"]
        assert db.surveys.count_documents({}) == 1
        assert db.surveys.find_one({"_id": before["_id"]}) == before
        assert db.responses.count_documents({}) == 0
    finally:
        client.close()


@pytest.mark.parametrize("bounds", [
    {"minimum": "-9.999999999999999999999999999999999e6144", "maximum": "9.999999999999999999999999999999999e6144"},
    {"minimum": "1e-6176", "maximum": "1e-6176"},
    {"minimum": "1.234567890123456789012345678901234"},
    {"minimum": None, "maximum": None},
])
def test_T26_legal_config_bounds_exact_storage(env, bounds):
    from decimal import Decimal
    db, _, owner = env
    s = create(owner, [question("number", validation=bounds)])
    stored = db.surveys.find_one({"_id": ObjectId(s["id"])})["questions"][0]["validation"]
    for field, value in bounds.items():
        if value is None:
            assert stored[field] is None
        else:
            assert isinstance(stored[field], Decimal128)
            assert stored[field].to_decimal() == Decimal(value)


@pytest.mark.parametrize("field", ["minChoices", "maxChoices", "minLength", "maxLength"])
def test_T26_other_config_bounds_reject_huge_integer(env, field):
    db, _, owner = env
    kind = "multiple" if "Choices" in field else "text"
    r = owner.request("POST", "/api/surveys", {"title": "invalid count", "questions": [question(kind, validation={field: 10**30})]})
    assert r.status_code == 422 and db.surveys.count_documents({}) == 0


def test_T27_submission_counts_and_distinct_accounts(env):
    db, app, owner = env
    s = publish(owner, create(owner, [
        question(jumpRules=[{"conditions": [{"op": "eq", "value": "c"}], "target": "END"}]),
        question("multiple", "q2"), question("text", "q3", required=False),
        question("number", "q4", required=False)], allowMultiple=True, allowAnonymous=True))
    alpha = Browser(app).account("alpha")
    beta = Browser(app).account("beta")
    try:
        for reader, choice, options, text, num, anonymous in [
            (alpha, "a", ["a", "b"], "甲", "10", True),
            (alpha, "b", ["b"], None, "20", False),
            (alpha, "c", None, None, None, True),
            (beta, "a", ["b", "c"], "乙", "30", True)]:
            answers = [{"questionId": "q1", "value": choice}]
            if options is not None:
                answers += [{"questionId": "q2", "value": options}, {"questionId": "q3", "value": text},
                            {"questionId": "q4", "value": num}]
            body = payload(answers, anonymous=anonymous)
            first = reader.request("POST", f"/api/fill/{s['token']}/submit", body)
            assert first.status_code == 200, first.text
            retry = reader.request("POST", f"/api/fill/{s['token']}/submit", body)
            assert retry.status_code == 200 and retry.json()["replayed"] is True
            assert retry.json()["responseId"] == first.json()["responseId"]
            saved = db.responses.find_one({"_id": ObjectId(first.json()["responseId"])})
            assert [a["questionId"] for a in saved["answers"]] == (
                ["q1"] if choice == "c" else ["q1", "q2", "q4"] if text is None else ["q1", "q2", "q3", "q4"])
        other = publish(owner, create(owner))
        assert alpha.request("POST", f"/api/fill/{other['token']}/submit", payload()).status_code == 200
        stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
        assert stats["total"] == 4 and stats["respondentCount"] == 2
        assert db.responses.count_documents({"surveyId": ObjectId(s["id"])}) == 4
        assert [(q["answered"], q["respondentCount"]) for q in stats["questions"]] == [(4, 2), (3, 2), (2, 2), (3, 2)]
        a, b, c, d = stats["questions"]
        assert [(o["count"], o["respondentCount"]) for o in a["options"]] == [(2, 2), (1, 1), (1, 1)]
        assert [(o["count"], o["respondentCount"]) for o in b["options"]] == [(1, 1), (3, 2), (1, 1)]
        assert {r["value"] for r in c["contents"]} == {"甲", "乙"}
        assert {r["author"] for r in c["contents"]} == {"匿名"}
        assert d["average"] == "20"
        assert {r["value"] for r in d["contents"]} == {"10", "20", "30"}
        assert not {"respondentId", "singleSubmissionKey", "payloadHash"} & set(str(stats).split("'"))
        for q in stats["questions"]:
            single = owner.request("GET", f"/api/surveys/{s['id']}/questions/{q['questionId']}/stats").json()
            assert single == q
        for skip in [0, 1, 2, 3]:
            page = owner.request("GET", f"/api/surveys/{s['id']}/questions/q4/stats?skip={skip}&limit=1").json()
            assert (page["answered"], page["respondentCount"], page["average"]) == (3, 2, "20")
        isolated = owner.request("GET", f"/api/surveys/{other['id']}/stats").json()
        assert (isolated["total"], isolated["respondentCount"]) == (1, 1)
    finally:
        alpha.client.close()
        beta.client.close()


# Stage two part one. Shared accounts/banks/cross-survey aggregation are deliberately absent.
def reusable(owner, kind="number", **content):
    q = question(kind, validation={"minimum": "0", "maximum": "120", "integer": True} if kind == "number" else {})
    data = {k: q[k] for k in ("kind", "title", "options", "validation") if k in q}
    data.update(content)
    r = owner.request("POST", "/api/reusable-questions", {"name": "年龄" if kind == "number" else "选择题",
        "creationKey": uuid.uuid4().hex, "content": data})
    assert r.status_code == 201, r.text
    return r.json()


def add_version(owner, q, content, base, **extra):
    root = owner.request("GET", f"/api/reusable-questions/{q['id']}").json()
    body = {"editRevision": root["editRevision"], "creationKey": uuid.uuid4().hex,
            "baseVersionId": base, "content": content, **extra}
    r = owner.request("POST", f"/api/reusable-questions/{q['id']}/versions", body)
    assert r.status_code == 200, r.text
    return r.json(), body


def add_to(owner, s, vid, **extra):
    body = {"versionId": vid, "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex, **extra}
    r = owner.request("POST", f"/api/surveys/{s['id']}/question-instances", body)
    assert r.status_code == 200, r.text
    return r.json(), body


def whole_body(s, **extra):
    return {**{k: s[k] for k in ("title", "description", "deadline", "allowAnonymous", "allowMultiple", "questions")},
            "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex, **extra}


def test_T28_version_instances_submission_and_old_snapshot(env):
    db, app, owner = env
    q = reusable(owner)
    v1 = q["latestVersion"]
    s, _ = add_to(owner, create(owner, []), v1["id"])
    s, _ = add_to(owner, s, v1["id"])
    a, b = [x["id"] for x in s["questions"]]
    assert a != b and all(x["sourceVersionId"] == v1["id"] for x in s["questions"])
    content = {**v1["content"], "title": "新年龄", "validation": {"maximum": "100", "integer": True}}
    v2, _ = add_version(owner, q, content, v1["id"])
    assert v2["versionNo"] == 2 and v2["parentVersionId"] == v1["id"]
    assert owner.request("GET", f"/api/surveys/{s['id']}").json()["questions"] == s["questions"]
    s = publish(owner, s)
    respondent = Browser(app).account("answerer")
    fill = respondent.request("GET", f"/api/fill/{s['token']}").json()
    assert not any({"sourceVersionId", "sourceQuestionId", "lastMutation"} & x.keys() for x in fill["questions"])
    body = payload([{ "questionId": a, "value": "10"}, {"questionId": b, "value": "20"}])
    response = respondent.request("POST", f"/api/fill/{s['token']}/submit", body)
    assert response.status_code == 200
    assert respondent.request("POST", f"/api/fill/{s['token']}/submit", body).json()["replayed"]
    stored = db.responses.find_one({"surveyId": ObjectId(s["id"])})
    assert stored["answers"] == [{"questionId": a, "value": Decimal128("10")}, {"questionId": b, "value": Decimal128("20")}]
    assert db.responses.count_documents({"surveyId": ObjectId(s["id"])}) == 1
    stats = owner.request("GET", f"/api/surveys/{s['id']}/stats").json()
    assert (stats["total"], stats["respondentCount"]) == (1, 1)
    assert [Decimal128(x["average"]).to_decimal() for x in stats["questions"]] == [10, 20]
    assert all(x["answered"] == 1 for x in stats["questions"])
    assert owner.request("POST", f"/api/surveys/{s['id']}/questions/{a}/upgrade", {
        "versionId": v2["id"], "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex}).status_code == 409


def test_T29_branch_restore_immutable_retry_permissions(env):
    db, app, owner = env
    q = reusable(owner)
    v1 = q["latestVersion"]
    before = db.questionVersions.find_one({"_id": ObjectId(v1["id"])})
    v2, body = add_version(owner, q, {**v1["content"], "title": "V2"}, v1["id"])
    assert owner.request("POST", f"/api/reusable-questions/{q['id']}/versions", body).json()["id"] == v2["id"]
    changed = {**body, "content": {**body["content"], "title": "不同输入"}}
    assert owner.request("POST", f"/api/reusable-questions/{q['id']}/versions", changed).status_code == 409
    v3, _ = add_version(owner, q, {**v1["content"], "title": "V3"}, v1["id"])
    root = owner.request("GET", f"/api/reusable-questions/{q['id']}").json()
    r = owner.request("POST", f"/api/reusable-questions/{q['id']}/restore", {"versionId": v1["id"],
        "editRevision": root["editRevision"], "creationKey": uuid.uuid4().hex})
    assert r.status_code == 200 and r.json()["versionNo"] == 4 and r.json()["content"] == v1["content"]
    assert v3["parentVersionId"] == v2["parentVersionId"] == v1["id"]
    history = owner.request("GET", f"/api/question-versions/{v3['id']}/history").json()
    assert [n["versionId"] for n in history["nodes"]] == [v3["id"], v1["id"]]
    assert db.questionVersions.find_one({"_id": ObjectId(v1["id"])}) == before
    other = Browser(app).account("intruder")
    assert other.request("GET", "/api/reusable-questions").json() == []
    for path in (f"/api/reusable-questions/{q['id']}", f"/api/reusable-questions/{q['id']}/versions",
                 f"/api/question-versions/{v1['id']}", f"/api/question-versions/{v1['id']}/history"):
        assert other.request("GET", path).status_code == 404
    foreign_s = create(other, [])
    assert other.request("POST", f"/api/surveys/{foreign_s['id']}/question-instances", {
        "versionId": v1["id"], "editRevision": 1, "operationKey": uuid.uuid4().hex}).status_code == 404


@pytest.mark.parametrize("whole", [False, True])
def test_T30_upgrade_validates_rules_atomically(env, whole):
    db, _, owner = env
    q = reusable(owner, "single")
    v1 = q["latestVersion"]
    s, _ = add_to(owner, create(owner, []), v1["id"])
    qid = s["questions"][0]["id"]
    body = whole_body(s)
    body["questions"][0]["jumpRules"] = [{"conditions": [{"op": "eq", "value": "a"}], "target": "END"}]
    s = owner.request("PUT", f"/api/surveys/{s['id']}", body).json()
    v2, _ = add_version(owner, q, {**v1["content"], "options": [{"id": "b", "label": "B"}, {"id": "c", "label": "C"}]}, v1["id"])
    before = db.surveys.find_one({"_id": ObjectId(s["id"])})
    if whole:
        body = whole_body(s)
        body["questions"][0]["sourceVersionId"] = v2["id"]
        r = owner.request("PUT", f"/api/surveys/{s['id']}", body)
    else:
        r = owner.request("POST", f"/api/surveys/{s['id']}/questions/{qid}/upgrade", {
            "versionId": v2["id"], "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex})
    assert r.status_code == 422, r.text
    assert db.surveys.find_one({"_id": ObjectId(s["id"])}) == before
    body = whole_body(s)
    body["questions"][0]["jumpRules"] = []
    body["questions"][0]["sourceVersionId"] = v2["id"]
    good = owner.request("PUT", f"/api/surveys/{s['id']}", body)
    assert good.status_code == 200 and good.json()["questions"][0]["id"] == qid
    assert good.json()["questions"][0]["options"] == v2["content"]["options"]


@pytest.mark.parametrize("failure", ["insert", "cleanup"])
def test_T31_interrupted_save_recover_without_original_request(env, monkeypatch, failure):
    from pymongo.collection import Collection
    db, app, owner = env
    original_insert, original_update = Collection.insert_one, Collection.update_one
    def insert(self, document, *args, **kwargs):
        if self.database.name == db.name and self.name == "questionVersions":
            raise RuntimeError("test injected interruption before version insert")
        return original_insert(self, document, *args, **kwargs)
    def update(self, query, document, *args, **kwargs):
        if self.database.name == db.name and self.name == "reusableQuestions" and "$unset" in document:
            raise RuntimeError("test injected interruption after version insert")
        return original_update(self, query, document, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(Collection, "insert_one" if failure == "insert" else "update_one", insert if failure == "insert" else update)
        with pytest.raises(RuntimeError, match="test injected"):
            reusable(owner)
    # No original POST body/key is used again; recover through persisted owner state.
    fresh = Browser(app)
    assert fresh.request("POST", "/api/login", {"username": "owner", "password": PASSWORD}).status_code == 200
    q = fresh.request("GET", "/api/reusable-questions").json()[0]
    p = q["pendingSave"]
    assert p and not p["needsRepair"]
    assert db.questionVersions.count_documents({}) == (0 if failure == "insert" else 1)
    recovery = {"editRevision": q["editRevision"], "operationId": p["operationId"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: fresh.request("POST", f"/api/reusable-questions/{q['id']}/recover-save", recovery), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert {r.json()["id"] for r in results} == {p["versionId"]}
    assert db.questionVersions.count_documents({}) == 1
    assert not db.reusableQuestions.find_one()["draft"]
    assert "pendingSave" not in db.reusableQuestions.find_one()
    assert fresh.request("GET", f"/api/question-versions/{p['versionId']}").json()["content"] == p["content"]


@pytest.mark.parametrize("whole", [False, True])
def test_T32_consistent_identity_retry_and_archival(env, whole):
    db, _, owner = env
    q = reusable(owner)
    v = q["latestVersion"]
    s = create(owner, [])
    if whole:
        body = whole_body(s, questions=[{"id": "temporary", **v["content"], "sourceQuestionId": q["id"], "sourceVersionId": v["id"]}])
        path, method = f"/api/surveys/{s['id']}", "PUT"
    else:
        body = {"versionId": v["id"], "editRevision": 1, "operationKey": uuid.uuid4().hex}
        path, method = f"/api/surveys/{s['id']}/question-instances", "POST"
    s = owner.request(method, path, body).json()
    again = owner.request(method, path, body)
    assert again.status_code == 200 and again.json()["editRevision"] == s["editRevision"]
    assert len(again.json()["questions"]) == 1
    changed = {**body, "title": "changed"} if whole else {**body, "required": False}
    assert owner.request(method, path, changed).status_code == 409
    local_id = s["questions"][0]["id"]
    for alteration in ({"sourceVersionId": None, "sourceQuestionId": None}, {"title": "forged"}):
        import copy
        bad = whole_body(copy.deepcopy(s))
        bad["questions"][0].update(alteration)
        before = db.surveys.find_one({"_id": ObjectId(s["id"])})
        assert owner.request("PUT", f"/api/surveys/{s['id']}", bad).status_code == 422
        assert db.surveys.find_one({"_id": ObjectId(s["id"])}) == before
    deletion = owner.request("DELETE", f"/api/surveys/{s['id']}/questions/{local_id}", {
        "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex})
    assert deletion.status_code == 200 and deletion.json()["questions"] == []
    assert owner.request(method, path, body).status_code == 409
    s, _ = add_to(owner, deletion.json(), v["id"])
    assert s["questions"][0]["id"] != local_id
    root = owner.request("GET", f"/api/reusable-questions/{q['id']}").json()
    assert owner.request("PATCH", f"/api/reusable-questions/{q['id']}", {"archived": True, "editRevision": root["editRevision"]}).status_code == 200
    kept = owner.request("PUT", f"/api/surveys/{s['id']}", whole_body(s))
    assert kept.status_code == 200
    assert owner.request("POST", f"/api/surveys/{s['id']}/question-instances", {"versionId": v["id"],
        "operationKey": uuid.uuid4().hex, "editRevision": kept.json()["editRevision"]}).status_code == 409


def test_T33_explicit_upgrade_preserves_legacy_data_and_exports(env, tmp_path, monkeypatch):
    import types
    from app.database import upgrade
    db, app, owner = env
    # A separate real stage-one database, initialized by the actual tagged program.
    legacy_db = db.client["survey_course_test_" + uuid.uuid4().hex]
    legacy = types.ModuleType("stage1_database")
    exec(subprocess.check_output(["git", "show", "stage1-final:app/database.py"]).decode("utf-8"), legacy.__dict__)
    try:
        legacy.initialize(legacy_db)
        user = db.users.find_one({"usernameKey": "owner"})
        legacy_db.users.insert_one(user)
        s = publish(owner, create(owner, [question("number")], allowMultiple=True))
        body = payload([{ "questionId": "q1", "value": "12"}])
        assert owner.request("POST", f"/api/fill/{s['token']}/submit", body).status_code == 200
        old_s = db.surveys.find_one({"_id": ObjectId(s["id"])})
        old_s["schemaVersion"] = 1
        legacy_db.surveys.insert_one(old_s)
        old_r = db.responses.find_one({"surveyId": old_s["_id"]})
        legacy_db.responses.insert_one(old_r)
        with pytest.raises(RuntimeError, match="explicit migration"):
            initialize(legacy_db)
        import runpy
        from pymongo.database import Database
        tools = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/upgrade-db.py"))
        backup = tools["backup_database"](legacy_db, tmp_path / "stage-one-backup")
        restored = db.client["survey_course_test_" + uuid.uuid4().hex]
        try:
            tools["restore_database"](restored, backup)
            legacy.initialize(restored)
            assert restored.surveys.find_one() == old_s and restored.responses.find_one() == old_r
            assert restored.users.find_one() == user
            with pytest.raises(RuntimeError, match="empty"):
                tools["restore_database"](restored, backup)
        finally:
            db.client.drop_database(restored.name)
        original_command = Database.command
        def interrupted(self, *args, **kwargs):
            result = original_command(self, *args, **kwargs)
            if self.name == legacy_db.name and args[:2] == ("collMod", "surveys"):
                raise RuntimeError("test injected migration interruption")
            return result
        with monkeypatch.context() as m:
            m.setattr(Database, "command", interrupted)
            with pytest.raises(RuntimeError, match="test injected migration"):
                upgrade(legacy_db)
        with pytest.raises(RuntimeError, match="Incomplete migration"):
            initialize(legacy_db)
        upgrade(legacy_db)
        upgrade(legacy_db)
        initialize(legacy_db)
        assert legacy_db.surveys.find_one() == old_s and legacy_db.responses.find_one() == old_r
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            legacy.initialize(legacy_db)
        with TestClient(create_app(legacy_db)) as client:
            client.headers["x-csrf-token"] = client.get("/api/session").json()["csrf"]
            assert client.post("/api/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
            response = client.post(f"/api/surveys/{s['id']}/questions/q1/save-as-reusable", json={"name": "旧年龄", "operationKey": "legacy-export-key"})
            assert response.status_code == 200, response.text
            assert response.json()["latestVersion"]["content"]["kind"] == "number"
            exported_version = response.json()["latestVersion"]["id"]
            exported_stats = client.get(f"/api/question-versions/{exported_version}/stats").json()
            assert (exported_stats["answerCount"], exported_stats["responseCount"], exported_stats["respondentCount"]) == (0, 0, 0)
            assert legacy_db.surveys.find_one() == old_s and legacy_db.responses.find_one() == old_r
            stats = client.get(f"/api/surveys/{s['id']}/stats").json()
            assert stats["total"] == 1 and stats["questions"][0]["average"] == "12"
            # Same old submission still has its original idempotency identity.
            assert client.post(f"/api/fill/{s['token']}/submit", json=body).json()["replayed"]
            assert client.post(f"/api/fill/{s['token']}/submit", json=payload([{"questionId": "q1", "value": "14"}])).status_code == 200
            assert legacy_db.responses.count_documents({"surveyId": old_s["_id"]}) == 2
            assert legacy_db.responses.find_one({"_id": old_r["_id"]}) == old_r
            assert client.get(f"/api/surveys/{s['id']}/stats").json()["questions"][0]["average"] == "13"
            draft = {**old_s, "_id": ObjectId(), "token": uuid.uuid4().hex, "status": "draft"}
            legacy_db.surveys.insert_one(draft)
            edited = client.put(f"/api/surveys/{draft['_id']}", json={"title": "旧草稿继续编辑",
                "questions": public(old_s["questions"]), "editRevision": draft["editRevision"]})
            assert edited.status_code == 200 and edited.json()["schemaVersion"] == 2
            assert edited.json()["questions"][0]["id"] == "q1"

    finally:
        assert legacy_db.name.startswith("survey_course_test_")
        db.client.drop_database(legacy_db.name)


@pytest.mark.parametrize("future", ["version", "validator"])
def test_T33_new_program_rejects_unknown_schema_without_mutation(env, future):
    import copy
    db, _, owner = env
    s = create(owner)
    validator = copy.deepcopy(db.surveys.options()["validator"])
    if future == "version":
        validator["$jsonSchema"]["properties"]["schemaVersion"]["enum"] = [1, 2, 3]
    else:
        validator["$jsonSchema"]["properties"]["unknownSemantics"] = {"bsonType": "string"}
    db.command("collMod", "surveys", validator=validator)
    if future == "version":
        db.surveys.update_one({"_id": ObjectId(s["id"])}, {"$set": {"schemaVersion": 3}})
    before = {name: db[name].options() for name in db.list_collection_names()}
    with pytest.raises(RuntimeError, match="Unsupported schema"):
        initialize(db)
    assert before == {name: db[name].options() for name in db.list_collection_names()}


@pytest.mark.parametrize("whole", [False, True])
def test_T30_delete_referenced_position_requires_atomic_rule_update(env, whole):
    db, _, owner = env
    q = reusable(owner)
    s, _ = add_to(owner, create(owner, [question(id="lead")]), q["latestVersion"]["id"])
    target = s["questions"][1]["id"]
    body = whole_body(s)
    body["questions"][0]["jumpRules"] = [{"conditions": [{"op": "eq", "value": "a"}], "target": target}]
    s = owner.request("PUT", f"/api/surveys/{s['id']}", body).json()
    before = db.surveys.find_one({"_id": ObjectId(s["id"])})
    if whole:
        body = whole_body(s, questions=s["questions"][:1])
        r = owner.request("PUT", f"/api/surveys/{s['id']}", body)
    else:
        body = {"editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex}
        r = owner.request("DELETE", f"/api/surveys/{s['id']}/questions/{target}", body)
    assert r.status_code == 422 and db.surveys.find_one({"_id": ObjectId(s["id"])}) == before
    if whole:
        body["questions"][0]["jumpRules"] = []
        r = owner.request("PUT", f"/api/surveys/{s['id']}", body)
    else:
        body["ruleUpdates"] = {"lead": []}
        r = owner.request("DELETE", f"/api/surveys/{s['id']}/questions/{target}", body)
    assert r.status_code == 200 and [x["id"] for x in r.json()["questions"]] == ["lead"]
    assert r.json()["questions"][0]["jumpRules"] == []


def test_T29_concurrent_version_save_same_key(env):
    db, _, owner = env
    q = reusable(owner)
    body = {"editRevision": q["editRevision"], "creationKey": "concurrent-version-key",
            "baseVersionId": q["latestVersion"]["id"], "content": {**q["latestVersion"]["content"], "title": "新版"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: owner.request("POST", f"/api/reusable-questions/{q['id']}/versions", body), range(2)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert db.questionVersions.count_documents({"questionId": ObjectId(q["id"])}) == 2


def test_T31_damaged_pending_is_visible_but_not_committed(env, monkeypatch):
    from pymongo.collection import Collection
    db, _, owner = env
    original = Collection.insert_one
    def interrupted(self, *args, **kwargs):
        if self.database.name == db.name and self.name == "questionVersions":
            raise RuntimeError("test injected interruption")
        return original(self, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(Collection, "insert_one", interrupted)
        with pytest.raises(RuntimeError, match="test injected"):
            reusable(owner)
    root = db.reusableQuestions.find_one()
    db.reusableQuestions.update_one({"_id": root["_id"]}, {"$unset": {"pendingSave.content": ""}})
    before = db.reusableQuestions.find_one()
    visible = owner.request("GET", "/api/reusable-questions").json()[0]
    assert visible["pendingSave"]["needsRepair"] and visible["pendingSave"]["content"] is None
    response = owner.request("POST", f"/api/reusable-questions/{visible['id']}/recover-save", {
        "editRevision": visible["editRevision"], "operationId": visible["pendingSave"]["operationId"]})
    assert response.status_code == 409 and db.reusableQuestions.find_one() == before
    assert db.questionVersions.count_documents({}) == 0



def test_T32_instance_limit_returns_validation_error_without_write(env):
    db, _, owner = env
    q = reusable(owner)
    s = create(owner, [question("text", f"q{i}") for i in range(100)])
    before = db.surveys.find_one({"_id": ObjectId(s["id"])})
    r = owner.request("POST", f"/api/surveys/{s['id']}/question-instances", {
        "versionId": q["latestVersion"]["id"], "editRevision": s["editRevision"], "operationKey": uuid.uuid4().hex})
    assert r.status_code == 422
    assert db.surveys.find_one({"_id": ObjectId(s["id"])}) == before


# Stage two part two: expectations are fixed from the confirmed business rules.
def share_with(owner, vid, name):
    r = owner.request("POST", f"/api/question-versions/{vid}/shares", {"username": name})
    assert r.status_code == 200, r.text
    return r.json()


def revoke(owner, entry):
    r = owner.request("DELETE", f"/api/question-versions/{entry['versionId']}/shares/{entry['recipientId']}",
                      {"editRevision": entry["editRevision"]})
    assert r.status_code == 200, r.text
    return r.json()


def submit_values(who, s, values, **extra):
    body = payload([{"questionId": q["id"], "value": value} for q, value in zip(s["questions"], values)], **extra)
    r = who.request("POST", f"/api/fill/{s['token']}/submit", body)
    assert r.status_code == 200, r.text
    assert who.request("POST", f"/api/fill/{s['token']}/submit", body).json()["replayed"]
    return r.json()


@pytest.mark.parametrize("whole", [False, True])
def test_T35_shared_revoke_preserves_existing_but_blocks_new(env, whole):
    db, app, owner = env
    receiver = Browser(app).account("receiver")
    outsider = Browser(app).account("outsider")
    q = reusable(owner); v1 = q["latestVersion"]
    v2, _ = add_version(owner, q, {**v1["content"], "title": "private newer"}, v1["id"])
    share = share_with(owner, v1["id"], "RECEIVER")
    assert receiver.request("GET", f"/api/question-versions/{v1['id']}").status_code == 200
    assert receiver.request("GET", f"/api/question-versions/{v2['id']}").status_code == 404
    for path in (f"/api/reusable-questions/{q['id']}", f"/api/reusable-questions/{q['id']}/versions", f"/api/question-versions/{v1['id']}/shares"):
        assert receiver.request("GET", path).status_code == 404
    assert outsider.request("GET", "/api/shared-question-versions").json() == []
    s, _ = add_to(receiver, create(receiver, []), v1["id"])
    body = {"name": "mine", "creationKey": "derive-fixed-key"}
    derived = receiver.request("POST", f"/api/question-versions/{v1['id']}/derive", body)
    assert derived.status_code == 200
    d = derived.json(); assert d["latestVersion"]["parentVersionId"] == v1["id"]
    revoked = revoke(owner, share)
    assert receiver.request("GET", "/api/shared-question-versions").json() == []
    assert receiver.request("GET", f"/api/question-versions/{v1['id']}").status_code == 404
    before = db.surveys.find_one({"_id": ObjectId(s["id"])})
    if whole:
        b = whole_body(s, questions=s["questions"] + [{**s["questions"][0], "id": "another"}])
        blocked = receiver.request("PUT", f"/api/surveys/{s['id']}", b)
    else:
        blocked = receiver.request("POST", f"/api/surveys/{s['id']}/question-instances", {
            "versionId": v1["id"], "editRevision": s["editRevision"], "operationKey": "new-use-after-revoke"})
    assert blocked.status_code == 404 and db.surveys.find_one({"_id": ObjectId(s["id"])}) == before
    assert receiver.request("POST", f"/api/question-versions/{v1['id']}/derive", {**body, "creationKey": "new-derived-key"}).status_code == 404
    assert receiver.request("POST", f"/api/surveys/{s['id']}/questions/{s['questions'][0]['id']}/save-as-reusable", {
        "name": "bypass", "operationKey": "no-export-bypass"}).status_code == 404
    # Retained positions can still be arranged/published; owned derivatives survive.
    b = whole_body(s); b["questions"][0]["required"] = False
    saved = receiver.request("PUT", f"/api/surveys/{s['id']}", b)
    assert saved.status_code == 200
    s = publish(receiver, saved.json());submit_values(receiver, s, ["10"])
    stats = receiver.request("GET", f"/api/question-versions/{v1['id']}/stats").json()
    assert (stats["answerCount"], stats["responseCount"], stats["respondentCount"], stats["average"]) == (1,1,1,"10")
    history = receiver.request("GET", f"/api/question-versions/{d['latestVersion']['id']}/history").json()
    assert history["nodes"][1] == {"versionId": v1["id"], "accessible": False, "version": None}
    assert "private newer" not in json.dumps(history)
    own_version, _ = add_version(receiver, d, {**d["latestVersion"]["content"], "title": "independent"}, d["latestVersion"]["id"])
    assert own_version["versionNo"] == 2
    # Same admitted derivation retries return the same resource even after revocation.
    assert receiver.request("POST", f"/api/question-versions/{v1['id']}/derive", body).json()["id"] == d["id"]
    assert owner.request("PUT", f"/api/question-versions/{v1['id']}/shares/{share['recipientId']}",
                         {"editRevision": share["editRevision"]}).status_code == 409
    assert owner.request("PUT", f"/api/question-versions/{v1['id']}/shares/{share['recipientId']}",
                         {"editRevision": revoked["editRevision"]}).status_code == 200
    assert db.questionShares.count_documents({}) == 1


def test_T36_bank_versions_restricted_placeholders_and_ownership(env):
    db, app, owner = env
    other = Browser(app).account("bankreader")
    q = reusable(owner);v1 = q["latestVersion"]
    v2, _ = add_version(owner, q, {**v1["content"], "title": "new age"}, v1["id"])
    banks = [owner.request("POST", "/api/question-banks", {"name": n}).json() for n in ("base", "other")]
    def put(who, bid, vid):
        r = who.request("POST", f"/api/question-banks/{bid}/items", {"versionId": vid})
        assert r.status_code == 200,r.text
        return r.json()
    i1 = put(owner,banks[0]["id"],v1["id"]);i2=put(owner,banks[1]["id"],v1["id"])
    assert put(owner,banks[0]["id"],v1["id"])["id"] == i1["id"]
    assert owner.request("PATCH", f"/api/question-banks/{banks[0]['id']}/items/{i1['id']}", {
        "editRevision": i1["editRevision"], "versionId": v2["id"]}).status_code == 200
    assert owner.request("GET", f"/api/question-banks/{banks[1]['id']}/items").json()[0]["selectedVersionId"] == v1["id"]
    assert other.request("GET", f"/api/question-banks/{banks[0]['id']}/items").status_code == 404
    share = share_with(owner,v1["id"],"bankreader")
    private = other.request("POST", "/api/question-banks", {"name": "shared items"}).json()
    item = put(other,private["id"],v1["id"])
    revoke(owner,share)
    hidden=other.request("GET",f"/api/question-banks/{private['id']}/items").json()[0]
    assert hidden["accessible"] is False and hidden["selectable"] is False and hidden["version"] is None
    assert other.request("DELETE", f"/api/question-banks/{private['id']}/items/{item['id']}", {"editRevision":item["editRevision"]}).status_code == 200
    archived=owner.request("PATCH",f"/api/question-banks/{banks[1]['id']}",{"editRevision":1,"archived":True}).json()
    assert owner.request("GET", f"/api/question-banks/{banks[1]['id']}/items").json()[0]["selectable"] is False
    assert owner.request("POST", f"/api/question-banks/{banks[1]['id']}/items", {"versionId":v2["id"]}).status_code == 409
    assert owner.request("PATCH",f"/api/question-banks/{banks[1]['id']}",{"editRevision":archived["editRevision"],"archived":False}).status_code == 200
    assert db.questionVersions.count_documents({}) == 2


def test_T37_exact_numeric_aggregation_scope_pagination(env):
    db, app, owner=env
    q=reusable(owner);v=q["latestVersion"]
    s1,_=add_to(owner,create(owner,[],allowMultiple=True),v["id"])
    s1,_=add_to(owner,s1,v["id"],required=False);s1=publish(owner,s1)
    s2,_=add_to(owner,create(owner,[],allowMultiple=True),v["id"]);s2=publish(owner,s2)
    a=Browser(app).account("numericA");b=Browser(app).account("numericB")
    submit_values(a,s1,["10","20"]);submit_values(a,s1,["30",None]);submit_values(a,s2,["40"],anonymous=False);submit_values(b,s2,["50"])
    # Same version used by someone else, another version and a derivative must not enter scope.
    share_with(owner,v["id"],"numericB")
    foreign,_=add_to(b,create(b,[]),v["id"]);foreign=publish(b,foreign);submit_values(b,foreign,["100"])
    v2,_=add_version(owner,q,{**v["content"],"title":"age2"},v["id"])
    distinct,_=add_to(owner,create(owner,[]),v2["id"]);distinct=publish(owner,distinct);submit_values(a,distinct,["90"])
    d=owner.request("POST",f"/api/question-versions/{v['id']}/derive",{"name":"copy","creationKey":"stats-derived-key"}).json()
    derived,_=add_to(owner,create(owner,[]),d["latestVersion"]["id"]);derived=publish(owner,derived);submit_values(a,derived,["80"])
    url=f"/api/question-versions/{v['id']}"
    r=owner.request("GET",url+"/stats");assert r.status_code==200,r.text
    data=r.json();assert (data["answerCount"],data["responseCount"],data["respondentCount"] )==(5,4,2)
    assert (Decimal128(data["average"]),Decimal128(data["minimum"]),Decimal128(data["maximum"]))==(Decimal128("30"),Decimal128("10"),Decimal128("50"))
    assert set(data["surveyIds"])=={s1["id"],s2["id"]}
    filtered=owner.request("GET",url+f"/stats?surveyId={s1['id']}").json()
    assert (filtered["answerCount"],filtered["responseCount"],filtered["respondentCount"] )==(3,2,1)
    assert owner.request("GET",url+f"/stats?surveyId={s1['id']}&surveyId={foreign['id']}").status_code==404
    # Tie all submission times: full ordering must still preserve every local position.
    db.responses.update_many({}, {"$set":{"submittedAt":now()}})
    details=[];distribution=[]
    for skip in (0,2,4):
        page=owner.request("GET",url+f"/contents?skip={skip}&limit=2").json();details+=page["items"]
        assert page["hasMore"]==(skip<4)
        page=owner.request("GET",url+f"/distribution?skip={skip}&limit=2").json();distribution+=page["items"]
        assert page["hasMore"]==(skip<4)
    assert len({r["entryId"] for r in details})==5 and sorted(int(r["value"]) for r in details)==[10,20,30,40,50]
    assert [int(r["value"]) for r in distribution]==[10,20,30,40,50] and all(r["answerCount"]==1 for r in distribution)
    assert sorted(r["author"] for r in details)==["numericA","匿名","匿名","匿名","匿名"]
    assert all("respondentId" not in row for row in details)
    usages=owner.request("GET",f"/api/reusable-questions/{q['id']}/usages").json()
    assert usages["scope"]=="ownedSurveys" and {i["surveyId"] for i in usages["items"]}=={s1["id"],s2["id"],distinct["id"]}
    assert all(i["surveyId"]!=foreign["id"] for i in usages["items"])
    assert next(i for i in usages["items"] if i["surveyId"]==s1["id"])["occurrenceCount"]==2


@pytest.mark.parametrize("kind",["single","multiple"])
def test_T38_option_counts_are_entries_responses_accounts(env,kind):
    db,app,owner=env;q=reusable(owner,kind);v=q["latestVersion"]
    s,_=add_to(owner,create(owner,[],allowMultiple=True),v["id"])
    s,_=add_to(owner,s,v["id"],required=False);s=publish(owner,s)
    def value(x): return [x] if kind=="multiple" else x
    submit_values(owner,s,[value("a"),value("a")]);submit_values(owner,s,[value("b"),None])
    r=owner.request("GET",f"/api/question-versions/{v['id']}/stats").json()
    assert (r["answerCount"],r["responseCount"],r["respondentCount"])==(3,2,1)
    assert [(x["answerCount"],x["responseCount"],x["respondentCount"]) for x in r["options"]]==[(2,1,1),(1,1,1),(0,0,0)]
    assert owner.request("GET",f"/api/question-versions/{v['id']}/contents").status_code==422
    # First-stage whole-survey count still means submissions, not entries.
    old=owner.request("GET",f"/api/surveys/{s['id']}/stats").json();assert old["total"]==2


def test_T39_empty_text_numeric_group_and_contracts(env):
    from app.contracts import CrossStatsOut
    from pydantic import ValidationError
    db,app,owner=env
    for kind in ("text","number"):
        q=reusable(owner,kind);v=q["latestVersion"]
        empty=owner.request("GET",f"/api/question-versions/{v['id']}/stats").json()
        assert (empty["answerCount"],empty["responseCount"],empty["respondentCount"])==(0,0,0)
        assert empty["average"] is None
        with pytest.raises(ValidationError):
            CrossStatsOut.model_validate({k:x for k,x in empty.items() if k!="answerCount"})
        s,_=add_to(owner,create(owner,[],allowMultiple=True),v["id"]);s=publish(owner,s)
        values=["1","1.0"] if kind=="number" else [" hello ","world"]
        for x in values: submit_values(owner,s,[x])
        detail=owner.request("GET",f"/api/question-versions/{v['id']}/contents").json()
        assert sorted(r["value"] for r in detail["items"])==(["1","1.0"] if kind=="number" else ["hello","world"])
        if kind=="number":
            distribution=owner.request("GET",f"/api/question-versions/{v['id']}/distribution").json()
            assert len(distribution["items"])==1 and distribution["items"][0]["answerCount"]==2
        else:
            assert owner.request("GET",f"/api/question-versions/{v['id']}/distribution").status_code==422


def test_T40_part_one_database_requires_explicit_expansion(env,monkeypatch):
    from app.database import initialize,upgrade
    db,app,owner=env
    s=create(owner);q=reusable(owner);before=db.surveys.find_one()
    for name in ("questionShares","questionBanks","questionBankItems"):
        db.drop_collection(name)
    with pytest.raises(RuntimeError,match="Incomplete migration"):
        initialize(db)
    upgrade(db);upgrade(db);initialize(db)
    assert db.surveys.find_one()==before and db.questionVersions.count_documents({})==1
    assert {"questionShares","questionBanks","questionBankItems"}<=set(db.list_collection_names())


@pytest.mark.parametrize("admitted",[False,True])
def test_T35_revocation_recovery_and_last_authorization_admission(env,monkeypatch,admitted):
    from pymongo.collection import Collection
    db,app,owner=env;receiver=Browser(app).account("recoverreader")
    q=reusable(owner);v=q["latestVersion"];entry=share_with(owner,v["id"],"recoverreader")
    original=Collection.insert_one
    triggered=False
    def insert(self,document,*args,**kwargs):
        nonlocal triggered
        if self.database.name==db.name and self.name==("reusableQuestions" if admitted else "questionVersions"):
            if admitted and not triggered:
                triggered=True
                revoke(owner,entry)
            elif not admitted:
                raise RuntimeError("explicit interrupted derivation")
        return original(self,document,*args,**kwargs)
    body={"name":"received","creationKey":"admitted-derivation"}
    with monkeypatch.context() as m:
        m.setattr(Collection,"insert_one",insert)
        if admitted:
            result=receiver.request("POST",f"/api/question-versions/{v['id']}/derive",body)
            assert result.status_code==200,result.text
        else:
            with pytest.raises(RuntimeError,match="explicit interrupted"):
                receiver.request("POST",f"/api/question-versions/{v['id']}/derive",body)
    if not admitted:
        revoke(owner,entry)
        pending=receiver.request("GET","/api/reusable-questions").json()[0]
        assert pending["pendingSave"] and pending["latestVersion"] is None
        result=receiver.request("POST",f"/api/reusable-questions/{pending['id']}/recover-save",{
            "editRevision":pending["editRevision"],"operationId":pending["pendingSave"]["operationId"]})
        assert result.status_code==200,result.text
    assert db.questionVersions.count_documents({})==2
    assert receiver.request("POST",f"/api/question-versions/{v['id']}/derive",{**body,"creationKey":"new-after-revoked"}).status_code==404


def test_T40_part_one_program_rejects_later_collections(env):
    db,app,owner=env
    namespace={"__name__":"stage2_part1_database"}
    source=subprocess.check_output(["git","show","cbaec6a:app/database.py"]).decode("utf-8")
    exec(compile(source,"stage2-part1/app/database.py","exec"),namespace)
    before={name:db[name].options() for name in db.list_collection_names()}
    with pytest.raises(RuntimeError,match="later application stage"):
        namespace["initialize"](db)
    assert before=={name:db[name].options() for name in db.list_collection_names()}


def test_T36_archived_question_and_exact_history_scope(env):
    db,app,owner=env;reader=Browser(app).account("historyreader")
    q=reusable(owner);v1=q["latestVersion"];v2,_=add_version(owner,q,{**v1["content"],"title":"shared-new"},v1["id"])
    share_with(owner,v2["id"],"historyreader")
    history=reader.request("GET",f"/api/question-versions/{v2['id']}/history").json()
    assert [n["accessible"] for n in history["nodes"]]==[True,False]
    assert history["nodes"][1]["version"] is None
    s,_=add_to(reader,create(reader,[]),v2["id"])
    before=db.surveys.find_one({"_id":ObjectId(s["id"])})
    fresh=owner.request("GET",f"/api/reusable-questions/{q['id']}").json()
    assert owner.request("PATCH",f"/api/reusable-questions/{q['id']}",{"editRevision":fresh["editRevision"],"archived":True}).status_code==200
    assert reader.request("GET","/api/shared-question-versions").json()==[]
    assert reader.request("GET",f"/api/question-versions/{v2['id']}").status_code==200
    assert reader.request("POST",f"/api/question-versions/{v2['id']}/derive",{"name":"blocked","creationKey":"archived-derived"}).status_code==409
    assert owner.request("POST",f"/api/question-versions/{v1['id']}/shares",{"username":"historyreader"}).status_code==409
    assert db.surveys.find_one({"_id":ObjectId(s["id"])})==before
    publish(reader,s)
