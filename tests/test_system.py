"""Real MongoDB integration tests. All test databases are generated and isolated."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from bson import Decimal128, ObjectId
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import WriteError

from app.database import initialize, now
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
    with TestClient(app):
        owner = Browser(app).account("owner")
        yield db, app, owner
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
    a, b, c, d = stats["questions"]
    assert [o["count"] for o in a["options"]] == [2, 1, 0]
    assert [o["count"] for o in b["options"]] == [2, 2, 0]
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
    broken = dict(stats["questions"][-1]); broken.pop("average")
    with pytest.raises(ValidationError):
        adapter.validate_python(broken)


@pytest.mark.parametrize("with_document", [False, True])
def test_T20_old_initializer_does_not_overwrite_future_schema(env, with_document):
    import copy
    db, _, owner = env
    s = create(owner)
    validator = copy.deepcopy(db.surveys.options()["validator"])
    validator["$jsonSchema"]["properties"]["schemaVersion"]["enum"] = [1, 2]
    db.command("collMod", "surveys", validator=validator)
    if with_document:
        db.surveys.update_one({"_id": ObjectId(s["id"])}, {"$set": {"schemaVersion": 2}})
    before = {name: db[name].options() for name in db.list_collection_names()}
    with pytest.raises(RuntimeError, match="Unsupported schema"):
        initialize(db)
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
