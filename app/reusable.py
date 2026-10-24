"""管理可复用题目与不可变版本，按准确版本检查读取权限。"""
import copy
import hashlib
import json
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .contracts import HistoryOut, ReusableOut, VersionOut
from .database import now, public
from .logic import fail, prepare_survey
from .models import (QuestionContent, ReusableCreate, ReusableUpdate, VersionSave,
                     RecoverSave, RestoreVersion, SurveyInput)
from .security import current_user

router = APIRouter(tags=["独立题目与版本"])
CONTENT_FIELDS = ("kind", "title", "options", "validation")


def object_id(value):
    if not ObjectId.is_valid(value):
        fail("题目或版本不存在", 404)
    return ObjectId(value)


def fingerprint(value):
    return hashlib.sha256(json.dumps(public(value), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def content_of(q):
    return copy.deepcopy({k: q[k] for k in CONTENT_FIELDS})


def prepare_content(model):
    q = {"id": "content", "required": False, **model.model_dump()}
    return content_of(prepare_survey(SurveyInput(title="内容检查", questions=[q]))["questions"][0])


def owned_question(db, qid, user):
    q = db.reusableQuestions.find_one({"_id": object_id(qid), "ownerId": user["_id"]})
    if not q:
        fail("题目不存在或无权访问", 404)
    return q


def can_read_version(db, v, user):
    if not v:
        return False
    q = db.reusableQuestions.find_one({"_id": v["questionId"]})
    return bool(q and (q["ownerId"] == user["_id"] or db.questionShares.find_one(
        {"versionId": v["_id"], "recipientId": user["_id"], "active": True})))


def readable_version(db, vid, user, selecting=False):
    v = db.questionVersions.find_one({"_id": object_id(vid)})
    q = db.reusableQuestions.find_one({"_id": v["questionId"]}) if v else None
    if not q or not can_read_version(db, v, user):
        fail("版本不存在或无权访问", 404)
    if selecting and q["archived"]:
        fail("题目已归档，不能新增选用或派生", 409)
    return v


def pending_view(p):
    if not p:
        return None
    try:
        QuestionContent.model_validate(public(p["content"]))
        healthy = all(k in p for k in ("operationId", "versionId", "versionNo", "requestHash", "parentVersionId", "snapshotHash", "admittedAt")) and isinstance(p.get("versionId"), ObjectId) and isinstance(p.get("versionNo"), int) and isinstance(p.get("operationId"), str) and isinstance(p.get("admittedAt"), datetime) and p.get("snapshotHash") == fingerprint({"content": p["content"], "parent": p["parentVersionId"]})
    except (KeyError, ValidationError):
        healthy = False
    return {"operationId": p.get("operationId"), "versionId": p.get("versionId"),
            "versionNo": p.get("versionNo"), "content": p.get("content") if healthy else None,
            "needsRepair": not healthy}


def question_view(db, q):
    return public({**q, "pendingSave": pending_view(q.get("pendingSave")),
                   "latestVersion": db.questionVersions.find_one({"questionId": q["_id"]}, sort=[("versionNo", -1)])})


def complete_save(db, q, pending):
    # 按预留的版本编号补齐写入；确认已有版本内容一致后才清除预留，支持中断恢复。
    if not pending or pending_view(pending)["needsRepair"]:
        fail("保存预留不完整，请核查备份；未丢弃原记录", 409)
    version = {"_id": pending["versionId"], "questionId": q["_id"], "versionNo": pending["versionNo"],
               "parentVersionId": pending["parentVersionId"], "content": pending["content"],
               "creationKey": pending["operationId"], "requestHash": pending["requestHash"],
               "createdAt": pending["admittedAt"], "schemaVersion": 2}
    existing = db.questionVersions.find_one({"questionId": q["_id"], "creationKey": pending["operationId"]})
    if not existing:
        try:
            db.questionVersions.insert_one(version)
            existing = version
        except DuplicateKeyError:
            existing = db.questionVersions.find_one({"_id": pending["versionId"]})
    if not existing or any(existing.get(k) != version[k] for k in
                           ("_id", "questionId", "versionNo", "parentVersionId", "requestHash")) or fingerprint(existing["content"]) != fingerprint(version["content"]):
        fail("保存预留与已有版本冲突，请核查；未覆盖任何版本", 409)
    db.reusableQuestions.update_one({"_id": q["_id"], "pendingSave.operationId": pending["operationId"]},
        {"$unset": {"pendingSave": ""}, "$set": {"draft": None, "updatedAt": now()}, "$inc": {"editRevision": 1}})
    return public(existing)


def new_question(db, user, body, parent=None, origin=None, key=None):
    content = prepare_content(body.content) if body.content else None
    name = body.name.strip()
    if not name:
        fail("管理名称不能为空")
    key = key or "create:" + body.creationKey
    hashed = fingerprint({"body": body.model_dump(), "parent": parent, "origin": origin})
    existing = db.reusableQuestions.find_one({"ownerId": user["_id"], "creationKey": key})
    if existing:
        if existing["requestHash"] != hashed:
            fail("同一创建键不能用于不同内容", 409)
        if existing.get("pendingSave"):
            complete_save(db, existing, existing["pendingSave"])
        return question_view(db, owned_question(db, existing["_id"], user))
    if parent:
        readable_version(db, parent, user, selecting=True)
    q = {"_id": ObjectId(), "ownerId": user["_id"], "name": name, "archived": False,
         "editRevision": 1, "nextVersionNo": 1, "creationKey": key, "requestHash": hashed,
         "draft": {"baseVersionId": parent, "content": content} if content else None,
         "createdAt": now(), "updatedAt": now(), "schemaVersion": 2}
    if origin:
        q["exportOrigin"] = origin
    if content and body.saveVersion:
        q["nextVersionNo"] = 2
        q["pendingSave"] = {"operationId": body.creationKey, "versionId": ObjectId(), "versionNo": 1,
                            "parentVersionId": parent, "content": content, "requestHash": hashed, "snapshotHash": fingerprint({"content": content, "parent": parent}), "admittedAt": now()}
    try:
        db.reusableQuestions.insert_one(q)
    except DuplicateKeyError:
        return new_question(db, user, body, parent, origin, key)
    if q.get("pendingSave"):
        complete_save(db, q, q["pendingSave"])
    return question_view(db, owned_question(db, q["_id"], user))


def save_version(db, user, qid, revision, key, content, parent, kind="save"):
    q = owned_question(db, qid, user)
    hashed = fingerprint({"content": content, "parent": parent, "kind": kind})
    existing = db.questionVersions.find_one({"questionId": q["_id"], "creationKey": key})
    if existing:
        if existing["requestHash"] != hashed:
            fail("同一版本保存键不能用于不同内容", 409)
        if q.get("pendingSave", {}).get("operationId") == key:
            complete_save(db, q, q["pendingSave"])
        return public(existing)
    if q.get("pendingSave"):
        p = q["pendingSave"]
        if p["operationId"] == key and p["requestHash"] == hashed:
            return complete_save(db, q, p)
        fail("存在待完成保存，请先完成中断保存", 409)
    if parent:
        base = readable_version(db, parent, user)
        if base["questionId"] != q["_id"]:
            fail("本系列新版本只能基于本系列版本")
    elif db.questionVersions.find_one({"questionId": q["_id"]}):
        fail("已有正式版时请选择本系列来源版本")
    pending = {"operationId": key, "versionId": ObjectId(), "versionNo": q["nextVersionNo"],
               "parentVersionId": parent, "content": content, "requestHash": hashed, "snapshotHash": fingerprint({"content": content, "parent": parent}), "admittedAt": now()}
    # 将编辑修订号与无待完成保存作为原子条件，同一次写入预留版本号，防止并发覆盖。
    reserved = db.reusableQuestions.find_one_and_update(
        {"_id": q["_id"], "editRevision": revision, "pendingSave": {"$exists": False}},
        {"$set": {"pendingSave": pending, "updatedAt": now()}, "$inc": {"editRevision": 1, "nextVersionNo": 1}},
        return_document=ReturnDocument.AFTER)
    if not reserved:
        latest = owned_question(db, qid, user)
        p = latest.get("pendingSave")
        existing = db.questionVersions.find_one({"questionId": q["_id"], "creationKey": key})
        if existing and existing["requestHash"] == hashed:
            return public(existing)
        if p and p["operationId"] == key and p["requestHash"] == hashed:
            return complete_save(db, latest, p)
        fail("内容已变化，请刷新后重试", 409)
    return complete_save(db, reserved, pending)


@router.get("/api/reusable-questions", response_model=list[ReusableOut])
def list_questions(request: Request, user=Depends(current_user), archived: bool = False,
                   skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    return [question_view(db, q) for q in db.reusableQuestions.find({"ownerId": user["_id"], "archived": archived})
            .sort([("updatedAt", -1), ("_id", -1)]).skip(skip).limit(limit)]


@router.post("/api/reusable-questions", status_code=201, response_model=ReusableOut)
def create_question(body: ReusableCreate, request: Request, user=Depends(current_user)):
    return new_question(request.app.state.db, user, body)


@router.get("/api/reusable-questions/{qid}", response_model=ReusableOut)
def get_question(qid: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    return question_view(db, owned_question(db, qid, user))


@router.patch("/api/reusable-questions/{qid}", response_model=ReusableOut)
def edit_question(qid: str, body: ReusableUpdate, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = owned_question(db, qid, user)
    changes = {}
    if body.name is not None:
        if not body.name.strip():
            fail("管理名称不能为空")
        changes["name"] = body.name.strip()
    if body.archived is not None:
        changes["archived"] = body.archived
    if "draft" in body.model_fields_set:
        draft = body.draft
        parent = object_id(draft.baseVersionId) if draft and draft.baseVersionId else None
        if parent and readable_version(db, parent, user)["questionId"] != q["_id"]:
            fail("草稿来源必须属于本系列")
        changes["draft"] = {"baseVersionId": parent, "content": prepare_content(draft.content)} if draft else None
    changed = db.reusableQuestions.find_one_and_update(
        {"_id": q["_id"], "editRevision": body.editRevision, "pendingSave": {"$exists": False}},
        {"$set": {**changes, "updatedAt": now()}, "$inc": {"editRevision": 1}}, return_document=ReturnDocument.AFTER)
    if not changed:
        fail("内容已变化或有待完成保存，请刷新", 409)
    return question_view(db, changed)


@router.get("/api/reusable-questions/{qid}/versions", response_model=list[VersionOut])
def list_versions(qid: str, request: Request, user=Depends(current_user), skip: int = Query(0, ge=0),
                  limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    q = owned_question(db, qid, user)
    return public(list(db.questionVersions.find({"questionId": q["_id"]}).sort("versionNo", -1).skip(skip).limit(limit)))


@router.post("/api/reusable-questions/{qid}/versions", response_model=VersionOut)
def create_version(qid: str, body: VersionSave, request: Request, user=Depends(current_user)):
    return save_version(request.app.state.db, user, qid, body.editRevision, body.creationKey,
                        prepare_content(body.content), object_id(body.baseVersionId) if body.baseVersionId else None)


@router.post("/api/reusable-questions/{qid}/restore", response_model=VersionOut)
def restore_version(qid: str, body: RestoreVersion, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = owned_question(db, qid, user)
    v = readable_version(db, body.versionId, user)
    if v["questionId"] != q["_id"]:
        fail("只能恢复本系列版本")
    return save_version(db, user, qid, body.editRevision, body.creationKey, v["content"], v["_id"], "restore")


@router.post("/api/reusable-questions/{qid}/recover-save", response_model=VersionOut)
def recover_save(qid: str, body: RecoverSave, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = owned_question(db, qid, user)
    p = q.get("pendingSave")
    if not p:
        existing = db.questionVersions.find_one({"questionId": q["_id"], "creationKey": body.operationId})
        if existing:
            return public(existing)
        fail("没有该待完成保存", 409)
    if q["editRevision"] != body.editRevision or p.get("operationId") != body.operationId:
        fail("待恢复状态已变化，请刷新", 409)
    return complete_save(db, q, p)


@router.get("/api/question-versions/{vid}", response_model=VersionOut)
def get_version(vid: str, request: Request, user=Depends(current_user)):
    return public(readable_version(request.app.state.db, vid, user))


@router.get("/api/question-versions/{vid}/history", response_model=HistoryOut)
def version_history(vid: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    current = readable_version(db, vid, user)
    nodes = []
    while current and len(nodes) < 100:
        nodes.append({"versionId": str(current["_id"]), "accessible": True, "version": public(current)})
        parent = current.get("parentVersionId")
        if not parent:
            current = None
            break
        v = db.questionVersions.find_one({"_id": parent})
        if not can_read_version(db, v, user):
            nodes.append({"versionId": str(parent), "accessible": False})
            current = None
            break
        current = v
    return {"nodes": nodes, "hasMore": current is not None, "nextVersionId": str(current["_id"]) if current else None}
