import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from bson import ObjectId
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from .contracts import (MessageOut, SessionOut, LoginOut, SurveySummaryOut, SurveyOut,
                        FillOut, WalkOut, PreviewOut, SubmitOut, StatsOut, QuestionStatsOut, ErrorOut)
from .database import connect, initialize, now, public
from .logic import deadline, fail, prepare_survey, validate_definition, walk
from .models import Credentials, MetadataUpdate, Revision, Submission, SurveyInput, SurveyUpdate, WalkInput
from .security import DUMMY_HASH, create_session, current_user, digest, hasher, username, verify

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"


def oid(value):
    if not ObjectId.is_valid(value):
        fail("问卷不存在", 404)
    return ObjectId(value)


def owned(db, survey_id, user):
    survey = db.surveys.find_one({"_id": oid(survey_id), "ownerId": user["_id"]})
    if not survey:
        fail("问卷不存在或无权访问", 404)
    return survey


def accessible(db, token):
    survey = db.surveys.find_one({"token": token, "status": "published"})
    if not survey or survey["deadline"] is not None and survey["deadline"] <= now():
        fail("问卷未开放、已截止或已关闭", 409)
    return survey


def ensure_available(db, survey, user):
    if not survey["allowMultiple"] and db.responses.find_one({"surveyId": survey["_id"], "singleSubmissionKey": user["_id"]}):
        fail("此问卷每个账号只能提交一次", 409)


def mutate(db, survey, user, revision, changes, required_status=None):
    query = {"_id": survey["_id"], "ownerId": user["_id"], "editRevision": revision}
    if required_status:
        query["status"] = required_status
    result = db.surveys.find_one_and_update(query, {"$set": {**changes, "updatedAt": now()}, "$inc": {"editRevision": 1}},
                                           return_document=ReturnDocument.AFTER)
    if not result:
        fail("内容已变化，请刷新后重试", 409)
    return public(result)


def question_stats(db, survey, question, skip=0, limit=20):
    base = [{"$match": {"surveyId": survey["_id"]}}, {"$unwind": "$answers"},
            {"$match": {"answers.questionId": question["id"]}}]
    counts = list(db.responses.aggregate(base + [{"$count": "n"}]))
    count = counts[0]["n"] if counts else 0
    result = {"questionId": question["id"], "title": question["title"], "kind": question["kind"], "answered": count}
    if question["kind"] in ("single", "multiple"):
        pipeline = base + ([{"$unwind": "$answers.value"}] if question["kind"] == "multiple" else [])
        totals = {row["_id"]: row["n"] for row in db.responses.aggregate(pipeline + [{"$group": {"_id": "$answers.value", "n": {"$sum": 1}}}])}
        result["options"] = [{**o, "count": totals.get(o["id"], 0)} for o in question["options"]]
    else:
        rows = list(db.responses.aggregate(base + [{"$sort": {"submittedAt": -1, "_id": -1}}, {"$skip": skip}, {"$limit": limit}]))
        # User references never leave this function; resolve names only for non-anonymous rows.
        user_ids = {r["respondentId"] for r in rows if not r["anonymous"]}
        names = {u["_id"]: u["username"] for u in db.users.find({"_id": {"$in": list(user_ids)}})}
        result["contents"] = [{"value": public(r["answers"]["value"]), "author": "匿名" if r["anonymous"] else names.get(r["respondentId"], "账号已不存在"),
                               "submittedAt": public(r["submittedAt"])} for r in rows]
        result.update({"skip": skip, "limit": limit, "hasMore": skip + len(rows) < count})
        if question["kind"] == "number":
            avg = list(db.responses.aggregate(base + [{"$group": {"_id": None, "average": {"$avg": "$answers.value"}}}]))
            result["average"] = public(avg[0]["average"]) if avg else None
    return result


def create_app(database=None):
    @asynccontextmanager
    async def lifespan(app):
        client = None
        if database is None:
            client, app.state.db = await run_in_threadpool(connect)
        else:
            app.state.db = database
        await run_in_threadpool(initialize, app.state.db)
        yield
        if client:
            client.close()

    app = FastAPI(title="MongoDB 问卷系统", version="1.0.0", lifespan=lifespan,
                  responses={code: {"model": ErrorOut} for code in (401, 403, 404, 409, 413, 422)})
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            cookie, header = request.cookies.get("survey_csrf"), request.headers.get("x-csrf-token")
            origin = request.headers.get("origin")
            if not cookie or not header or not secrets.compare_digest(cookie, header) or origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "请求校验失败，请刷新页面"}, status_code=403)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2_500_000:
                    return JSONResponse({"detail": "请求内容过大"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/survey/{token}", response_class=HTMLResponse, include_in_schema=False)
    def page(request: Request, token: str = ""):
        return templates.TemplateResponse(request=request, name="index.html", context={"token": token})

    @app.get("/api/session", tags=["账号"], response_model=SessionOut)
    def session(request: Request):
        csrf = request.cookies.get("survey_csrf") or secrets.token_urlsafe(32)
        try:
            user = current_user(request)
            data = {"id": str(user["_id"]), "username": user["username"]}
        except Exception as exc:
            from fastapi import HTTPException
            if not isinstance(exc, HTTPException) or exc.status_code != 401:
                raise
            data = None
        response = JSONResponse(SessionOut(user=data, csrf=csrf).model_dump(mode="json"))
        response.set_cookie("survey_csrf", csrf, httponly=True, samesite="lax", secure=COOKIE_SECURE)
        return response

    @app.post("/api/register", status_code=201, tags=["账号"], response_model=MessageOut)
    def register(body: Credentials, request: Request):
        display, key = username(body.username)
        try:
            request.app.state.db.users.insert_one({"username": display, "usernameKey": key,
                "passwordHash": hasher.hash(body.password), "createdAt": now(), "schemaVersion": 1})
        except DuplicateKeyError:
            fail("用户名已存在", 409)
        return {"message": "注册成功，请登录"}

    @app.post("/api/login", tags=["账号"], response_model=LoginOut)
    def login(body: Credentials, request: Request):
        _, key = username(body.username)
        db = request.app.state.db
        user = db.users.find_one({"usernameKey": key})
        if not verify(user["passwordHash"] if user else DUMMY_HASH, body.password) or not user:
            fail("用户名或密码错误", 401)
        old = request.cookies.get("survey_session")
        if old:
            db.sessions.delete_one({"tokenHash": digest(old)})
        token = create_session(db, user["_id"])
        response = JSONResponse(LoginOut(username=user["username"]).model_dump(mode="json"))
        response.set_cookie("survey_session", token, httponly=True, max_age=43200, samesite="lax", secure=COOKIE_SECURE)
        return response

    @app.post("/api/logout", tags=["账号"], response_model=MessageOut)
    def logout(request: Request):
        request.app.state.db.sessions.delete_one({"tokenHash": digest(request.cookies.get("survey_session", ""))})
        response = JSONResponse(MessageOut(message="已退出登录").model_dump(mode="json"))
        response.delete_cookie("survey_session")
        return response

    @app.get("/api/surveys", tags=["问卷管理"], response_model=list[SurveySummaryOut])
    def surveys(request: Request, user=Depends(current_user), skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        return public(list(request.app.state.db.surveys.find({"ownerId": user["_id"]}, {"questions": 0}).sort([("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit)))

    @app.post("/api/surveys", status_code=201, tags=["问卷管理"], response_model=SurveyOut)
    def create(body: SurveyInput, request: Request, user=Depends(current_user)):
        survey = {**prepare_survey(body), "ownerId": user["_id"], "token": secrets.token_urlsafe(18), "status": "draft",
                  "editRevision": 1, "definitionVersion": 1, "schemaVersion": 1, "createdAt": now(), "updatedAt": now()}
        request.app.state.db.surveys.insert_one(survey)
        return public(survey)

    @app.get("/api/surveys/{survey_id}", tags=["问卷管理"], response_model=SurveyOut)
    def get_survey(survey_id: str, request: Request, user=Depends(current_user)):
        return public(owned(request.app.state.db, survey_id, user))

    @app.put("/api/surveys/{survey_id}", tags=["问卷管理"], response_model=SurveyOut)
    def update(survey_id: str, body: SurveyUpdate, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = owned(db, survey_id, user)
        if survey["status"] != "draft":
            fail("已发布问卷的题目与设置已冻结，请使用基本信息接口", 409)
        return mutate(db, survey, user, body.editRevision, prepare_survey(body), "draft")

    @app.patch("/api/surveys/{survey_id}/metadata", tags=["问卷管理"], response_model=SurveyOut)
    def metadata(survey_id: str, body: MetadataUpdate, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = owned(db, survey_id, user)
        title = body.title.strip()
        if not title:
            fail("问卷标题不能为空")
        return mutate(db, survey, user, body.editRevision, {"title": title, "description": body.description, "deadline": deadline(body.deadline)})

    @app.post("/api/surveys/{survey_id}/publish", tags=["问卷管理"], response_model=SurveyOut)
    def publish(survey_id: str, body: Revision, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = owned(db, survey_id, user)
        validate_definition(survey, publishing=True)
        if survey["deadline"] is not None and survey["deadline"] <= now():
            fail("发布时截止时间应在未来")
        return mutate(db, survey, user, body.editRevision, {"status": "published"}, "draft")

    @app.post("/api/surveys/{survey_id}/close", tags=["问卷管理"], response_model=SurveyOut)
    def close(survey_id: str, body: Revision, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        return mutate(db, owned(db, survey_id, user), user, body.editRevision, {"status": "closed"}, "published")

    @app.get("/api/fill/{token}", tags=["填写"], response_model=FillOut)
    def fill(token: str, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = accessible(db, token)
        ensure_available(db, survey, user)
        return public({k: survey[k] for k in ("title", "description", "deadline", "questions", "allowAnonymous", "allowMultiple", "definitionVersion")})

    @app.post("/api/fill/{token}/walk", tags=["填写"], response_model=WalkOut)
    def traverse(token: str, body: WalkInput, request: Request, user=Depends(current_user)):
        survey = accessible(request.app.state.db, token)
        return walk(survey, body.answers)[0]

    @app.post("/api/surveys/{survey_id}/preview", tags=["问卷管理"], response_model=PreviewOut)
    def preview(survey_id: str, body: WalkInput, request: Request, user=Depends(current_user)):
        survey = owned(request.app.state.db, survey_id, user)
        validate_definition(survey, publishing=True)
        return {"survey": public({k: survey[k] for k in ("title", "description", "questions", "allowAnonymous", "allowMultiple")}),
                "walk": walk(survey, body.answers)[0]}

    @app.post("/api/fill/{token}/submit", tags=["填写"], response_model=SubmitOut)
    def submit(token: str, body: Submission, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = db.surveys.find_one({"token": token})
        if not survey:
            fail("问卷不存在", 404)
        payload_hash = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        retry_query = {"surveyId": survey["_id"], "respondentId": user["_id"], "submissionKey": body.submissionKey}
        def retry(existing):
            if existing["payloadHash"] != payload_hash:
                fail("同一提交键不能用于不同内容", 409)
            return {"message": "提交成功", "responseId": str(existing["_id"]), "replayed": True}
        existing = db.responses.find_one(retry_query)
        if existing:
            return retry(existing)
        accessible(db, token)
        ensure_available(db, survey, user)
        _, answers = walk(survey, body.answers, complete=True)
        # Last state/deadline read is admission. An admitted in-flight insert may finish after close.
        accessible(db, token)
        response = {**retry_query, "definitionVersion": survey["definitionVersion"], "anonymous": bool(body.anonymous and survey["allowAnonymous"]),
                    "answers": answers, "submittedAt": now(), "schemaVersion": 1, "payloadHash": payload_hash}
        if not survey["allowMultiple"]:
            response["singleSubmissionKey"] = user["_id"]
        try:
            db.responses.insert_one(response)
        except DuplicateKeyError:
            existing = db.responses.find_one(retry_query)
            if existing:
                return retry(existing)
            fail("此问卷每个账号只能提交一次", 409)
        return {"message": "提交成功", "responseId": str(response["_id"]), "replayed": False}

    @app.get("/api/surveys/{survey_id}/stats", tags=["统计"], response_model=StatsOut)
    def stats(survey_id: str, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = owned(db, survey_id, user)
        return {"total": db.responses.count_documents({"surveyId": survey["_id"]}),
                "questions": [question_stats(db, survey, q) for q in survey["questions"]]}

    @app.get("/api/surveys/{survey_id}/questions/{question_id}/stats", tags=["统计"], response_model=QuestionStatsOut)
    def one_stat(survey_id: str, question_id: str, request: Request, user=Depends(current_user),
                 skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        db = request.app.state.db
        survey = owned(db, survey_id, user)
        question = next((q for q in survey["questions"] if q["id"] == question_id), None)
        if not question:
            fail("题目不存在", 404)
        return question_stats(db, survey, question, skip, limit)

    return app


app = create_app()
