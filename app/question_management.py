"""Sharing, personal classification, owned usage and exact-version aggregation."""
from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .contracts import (RemovalOut, ReusableOut, ShareOut, SharedVersionOut, BankOut, BankItemOut,
                        UsagesOut, CrossStatsOut, CrossContentsOut, DistributionOut)
from .database import now, public
from .logic import fail
from .models import (DeriveQuestion, ReusableCreate, ShareCreate, Revision, BankCreate,
                     BankUpdate, BankItemCreate, BankItemUpdate)
from .reusable import (object_id, readable_version, can_read_version, owned_question,
                       new_question)
from .security import current_user, username

router = APIRouter(tags=["共享、题库与跨卷统计"])


def owned_version(db, vid, user):
    v = db.questionVersions.find_one({"_id": object_id(vid)})
    if not v:
        fail("版本不存在或无权访问", 404)
    owned_question(db, v["questionId"], user)
    return v


def share_view(db, share):
    u = db.users.find_one({"_id": share["recipientId"]})
    return public({**share, "username": u["username"] if u else "账号已不存在"})


@router.post("/api/question-versions/{vid}/derive", response_model=ReusableOut)
def derive(vid: str, body: DeriveQuestion, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    # new_question checks an existing receipt before current authorization, so an admitted
    # pending operation remains recoverable after revocation. No content escapes on denial.
    v = db.questionVersions.find_one({"_id": object_id(vid)})
    if not v:
        fail("版本不存在或无权访问", 404)
    return new_question(db, user, ReusableCreate(**body.model_dump(), content=public(v["content"])),
                        parent=v["_id"], key=f"derive:{vid}:{body.creationKey}")


@router.get("/api/question-versions/{vid}/shares", response_model=list[ShareOut])
def shares(vid: str, request: Request, user=Depends(current_user),
           skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    v = owned_version(db, vid, user)
    return [share_view(db, x) for x in db.questionShares.find({"versionId": v["_id"]})
            .sort("_id", 1).skip(skip).limit(limit)]


@router.post("/api/question-versions/{vid}/shares", response_model=ShareOut)
def grant(vid: str, body: ShareCreate, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    v = owned_version(db, vid, user)
    _, key = username(body.username)
    recipient = db.users.find_one({"usernameKey": key})
    if not recipient:
        fail("接收账号不存在", 404)
    if recipient["_id"] == user["_id"]:
        fail("本人已有所有权，无需共享")
    readable_version(db, vid, user, selecting=True)
    entry = {"versionId": v["_id"], "recipientId": recipient["_id"], "active": True,
             "editRevision": 1, "createdAt": now(), "revokedAt": None, "schemaVersion": 2}
    try:
        db.questionShares.insert_one(entry)
    except DuplicateKeyError:
        entry = db.questionShares.find_one({"versionId": v["_id"], "recipientId": recipient["_id"]})
        if not entry["active"]:
            fail("共享已撤销，请刷新列表后明确重新授权", 409)
    return share_view(db, entry)


@router.get("/api/question-versions/{vid}/shares/{uid}", response_model=ShareOut)
def get_share(vid: str, uid: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    v = owned_version(db, vid, user)
    entry = db.questionShares.find_one({"versionId": v["_id"], "recipientId": object_id(uid)})
    if not entry:
        fail("共享记录不存在", 404)
    return share_view(db, entry)


@router.put("/api/question-versions/{vid}/shares/{uid}", response_model=ShareOut)
@router.delete("/api/question-versions/{vid}/shares/{uid}", response_model=ShareOut)
def change_share(vid: str, uid: str, body: Revision, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    v = owned_version(db, vid, user)
    active = request.method == "PUT"
    if active:
        readable_version(db, vid, user, selecting=True)
    query = {"versionId": v["_id"], "recipientId": object_id(uid)}
    if not db.questionShares.find_one(query):
        fail("共享记录不存在", 404)
    changed = db.questionShares.find_one_and_update({**query, "editRevision": body.editRevision},
        {"$set": {"active": active, "revokedAt": None if active else now()}, "$inc": {"editRevision": 1}},
        return_document=ReturnDocument.AFTER)
    if not changed:
        fail("共享状态已变化，请刷新", 409)
    return share_view(db, changed)


@router.get("/api/shared-question-versions", response_model=list[SharedVersionOut])
def shared(request: Request, user=Depends(current_user), questionId: str | None = None, skip: int = Query(0, ge=0),
           limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    rows = db.questionShares.aggregate([
        {"$match": {"recipientId": user["_id"], "active": True}},
        {"$lookup": {"from": "questionVersions", "localField": "versionId", "foreignField": "_id", "as": "v"}},
        {"$unwind": "$v"},
        {"$match": {"v.questionId": object_id(questionId)} if questionId else {}},
        {"$lookup": {"from": "reusableQuestions", "localField": "v.questionId", "foreignField": "_id", "as": "q"}},
        {"$unwind": "$q"}, {"$match": {"q.archived": False}},
        {"$sort": {"versionId": 1}}, {"$skip": skip}, {"$limit": limit}])
    result = []
    for row in rows:
        owner = db.users.find_one({"_id": row["q"]["ownerId"]})
        result.append({"version": public(row["v"]), "owner": owner["username"] if owner else "账号已不存在"})
    return result


def owned_bank(db, bid, user):
    b = db.questionBanks.find_one({"_id": object_id(bid), "ownerId": user["_id"]})
    if not b:
        fail("题库不存在或无权访问", 404)
    return b


def bank_open(b):
    if b["archived"]:
        fail("题库已归档，请先取消归档", 409)


@router.get("/api/question-banks", response_model=list[BankOut])
def banks(request: Request, user=Depends(current_user), archived: bool = False,
          skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return public(list(request.app.state.db.questionBanks.find({"ownerId": user["_id"], "archived": archived})
                       .sort([("updatedAt", -1), ("_id", -1)]).skip(skip).limit(limit)))


@router.post("/api/question-banks", response_model=BankOut, status_code=201)
def create_bank(body: BankCreate, request: Request, user=Depends(current_user)):
    name = body.name.strip()
    if not name:
        fail("题库名称不能为空")
    b = {"ownerId": user["_id"], "name": name, "archived": False, "editRevision": 1,
         "createdAt": now(), "updatedAt": now(), "schemaVersion": 2}
    request.app.state.db.questionBanks.insert_one(b)
    return public(b)


@router.get("/api/question-banks/{bid}", response_model=BankOut)
def get_bank(bid: str, request: Request, user=Depends(current_user)):
    return public(owned_bank(request.app.state.db, bid, user))


@router.patch("/api/question-banks/{bid}", response_model=BankOut)
def update_bank(bid: str, body: BankUpdate, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    b = owned_bank(db, bid, user)
    changes = body.model_dump(exclude_none=True, exclude={"editRevision"})
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            fail("题库名称不能为空")
    result = db.questionBanks.find_one_and_update({"_id": b["_id"], "editRevision": body.editRevision},
        {"$set": {**changes, "updatedAt": now()}, "$inc": {"editRevision": 1}}, return_document=ReturnDocument.AFTER)
    if not result:
        fail("题库已变化，请刷新", 409)
    return public(result)


def item_view(db, item, user, bank):
    v = db.questionVersions.find_one({"_id": item["selectedVersionId"]})
    readable = can_read_version(db, v, user)
    q = db.reusableQuestions.find_one({"_id": item["questionId"]}) if readable else None
    return public({**item, "accessible": readable, "selectable": bool(readable and q and not q["archived"] and not bank["archived"]),
                   "version": v if readable else None})


@router.get("/api/question-banks/{bid}/items", response_model=list[BankItemOut])
def bank_items(bid: str, request: Request, user=Depends(current_user), skip: int = Query(0, ge=0),
               limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    b = owned_bank(db, bid, user)
    return [item_view(db, i, user, b) for i in db.questionBankItems.find({"bankId": b["_id"]})
            .sort([("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit)]


@router.post("/api/question-banks/{bid}/items", response_model=BankItemOut)
def add_item(bid: str, body: BankItemCreate, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    b = owned_bank(db, bid, user)
    bank_open(b)
    v = readable_version(db, body.versionId, user, selecting=True)
    item = {"bankId": b["_id"], "questionId": v["questionId"], "selectedVersionId": v["_id"], "editRevision": 1,
            "createdAt": now(), "updatedAt": now(), "schemaVersion": 2}
    try:
        db.questionBankItems.insert_one(item)
    except DuplicateKeyError:
        item = db.questionBankItems.find_one({"bankId": b["_id"], "questionId": v["questionId"]})
        if item["selectedVersionId"] != v["_id"]:
            fail("本库已有该题，请通过条目主动换版", 409)
    return item_view(db, item, user, b)


@router.patch("/api/question-banks/{bid}/items/{iid}", response_model=BankItemOut)
def update_item(bid: str, iid: str, body: BankItemUpdate, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    b = owned_bank(db, bid, user)
    bank_open(b)
    old = db.questionBankItems.find_one({"_id": object_id(iid), "bankId": b["_id"]})
    if not old:
        fail("条目不存在", 404)
    v = readable_version(db, body.versionId, user, selecting=True)
    if old["questionId"] != v["questionId"]:
        fail("条目只能换到同一系列的版本")
    result = db.questionBankItems.find_one_and_update({"_id": old["_id"], "editRevision": body.editRevision},
        {"$set": {"selectedVersionId": v["_id"], "updatedAt": now()}, "$inc": {"editRevision": 1}},
        return_document=ReturnDocument.AFTER)
    if not result:
        fail("条目已变化，请刷新", 409)
    return item_view(db, result, user, b)


@router.delete("/api/question-banks/{bid}/items/{iid}", response_model=RemovalOut)
def remove_item(bid: str, iid: str, body: Revision, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    b = owned_bank(db, bid, user)
    query = {"_id": object_id(iid), "bankId": b["_id"]}
    if not db.questionBankItems.find_one(query):
        fail("条目不存在", 404)
    if not db.questionBankItems.delete_one({**query, "editRevision": body.editRevision}).deleted_count:
        fail("条目已变化，请刷新", 409)
    return {"message": "已移除分类关联，题目和问卷未删除"}


def used_surveys(db, user, version_ids):
    return db.surveys.find({"ownerId": user["_id"], "questions.sourceVersionId": {"$in": version_ids}})


def version_context(db, vid, user):
    version_id = str(object_id(vid))
    surveys = list(used_surveys(db, user, [version_id]))
    v = db.questionVersions.find_one({"_id": ObjectId(version_id)})
    if can_read_version(db, v, user):
        content = public(v["content"])
    elif surveys:
        content = next(q for s in surveys for q in s["questions"] if q.get("sourceVersionId") == version_id)
    else:
        fail("版本不存在或无权访问", 404)
    return version_id, content, surveys


def usage_page(surveys, ids, skip, limit):
    items = []
    for s in surveys:
        grouped = {}
        for q in s["questions"]:
            if q.get("sourceVersionId") in ids:
                grouped.setdefault(q["sourceVersionId"], []).append(q["id"])
        for vid, positions in sorted(grouped.items()):
            items.append({"surveyId": str(s["_id"]), "title": s["title"], "status": s["status"],
                          "versionId": vid, "questionIds": positions, "occurrenceCount": len(positions)})
    items.sort(key=lambda i: (i["versionId"], i["surveyId"]))
    return {"scope": "ownedSurveys", "items": items[skip:skip+limit], "skip": skip, "limit": limit,
            "hasMore": skip+limit < len(items)}


@router.get("/api/reusable-questions/{qid}/usages", response_model=UsagesOut)
def series_usages(qid: str, request: Request, user=Depends(current_user), skip: int = Query(0, ge=0),
                  limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    q = owned_question(db, qid, user)
    ids = [str(v["_id"]) for v in db.questionVersions.find({"questionId": q["_id"]}, {"_id": 1})]
    return usage_page(used_surveys(db, user, ids), ids, skip, limit)


@router.get("/api/question-versions/{vid}/usages", response_model=UsagesOut)
def version_usages(vid: str, request: Request, user=Depends(current_user), skip: int = Query(0, ge=0),
                   limit: int = Query(20, ge=1, le=100)):
    version_id, _, surveys = version_context(request.app.state.db, vid, user)
    return usage_page(surveys, [version_id], skip, limit)


def statistical_context(db, vid, user, selected):
    version_id, content, surveys = version_context(db, vid, user)
    if selected is not None:
        ids = {object_id(x) for x in selected}
        if db.surveys.count_documents({"_id": {"$in": list(ids)}, "ownerId": user["_id"]}) != len(ids):
            fail("筛选中包含不存在或无权访问的问卷", 404)
        surveys = [s for s in surveys if s["_id"] in ids]
    clauses = [{"surveyId": s["_id"], "answers.questionId": {"$in": [q["id"] for q in s["questions"]
                if q.get("sourceVersionId") == version_id]}} for s in surveys]
    # Match each answer to its survey AND its exact local position; matching only the
    # version's question IDs across all surveys could count an unrelated normal position.
    base = [{"$match": {"surveyId": {"$in": [s["_id"] for s in surveys]}}}, {"$unwind": "$answers"},
            {"$match": {"$or": clauses} if clauses else {"_id": {"$exists": False}}},
            {"$match": {"answers.value": {"$nin": [None, "", []]}}}]
    return version_id, content, surveys, base


def counts(db, pipeline):
    rows = list(db.responses.aggregate(pipeline + [{"$facet": {
        "answers": [{"$count": "n"}],
        "responses": [{"$group": {"_id": "$_id"}}, {"$count": "n"}],
        "accounts": [{"$group": {"_id": "$respondentId"}}, {"$count": "n"}]}}]))[0]
    return {name: rows[key][0]["n"] if rows[key] else 0 for name, key in
            (("answerCount", "answers"), ("responseCount", "responses"), ("respondentCount", "accounts"))}


@router.get("/api/question-versions/{vid}/stats", response_model=CrossStatsOut)
def cross_stats(vid: str, request: Request, user=Depends(current_user),
                surveyId: list[str] | None = Query(default=None, max_length=100)):
    db = request.app.state.db
    version_id, content, surveys, base = statistical_context(db, vid, user, surveyId)
    result = {"versionId": version_id, "scope": "ownedSurveys", "surveyIds": [str(s["_id"]) for s in surveys],
              "title": content["title"], "kind": content["kind"], **counts(db, base),
              "options": [], "average": None, "minimum": None, "maximum": None}
    if content["kind"] in ("single", "multiple"):
        expanded = base + ([{"$unwind": "$answers.value"}] if content["kind"] == "multiple" else [])
        for o in content["options"]:
            result["options"].append({**o, **counts(db, expanded + [{"$match": {"answers.value": o["id"]}}])})
    elif content["kind"] == "number":
        summary = list(db.responses.aggregate(base + [{"$group": {"_id": None,
            "average": {"$avg": "$answers.value"}, "minimum": {"$min": "$answers.value"}, "maximum": {"$max": "$answers.value"}}}]))
        if summary:
            result.update({k: public(summary[0][k]) for k in ("average", "minimum", "maximum")})
    return result


@router.get("/api/question-versions/{vid}/contents", response_model=CrossContentsOut)
def cross_contents(vid: str, request: Request, user=Depends(current_user),
                   surveyId: list[str] | None = Query(default=None, max_length=100),
                   skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    _, content, surveys, base = statistical_context(db, vid, user, surveyId)
    if content["kind"] not in ("text", "number"):
        fail("只有文本和数字提供回答明细")
    rows = list(db.responses.aggregate(base + [{"$sort": {"submittedAt": -1, "_id": -1, "answers.questionId": 1}},
                                              {"$skip": skip}, {"$limit": limit+1}]))
    names = {u["_id"]: u["username"] for u in db.users.find({"_id": {"$in": list({r["respondentId"] for r in rows[:limit] if not r["anonymous"]})}})}
    titles = {s["_id"]: s["title"] for s in surveys}
    return {"items": [{"entryId": f"{r['_id']}:{r['answers']['questionId']}", "surveyId": str(r["surveyId"]),
                       "surveyTitle": titles[r["surveyId"]], "questionId": r["answers"]["questionId"],
                       "value": public(r["answers"]["value"]), "author": "匿名" if r["anonymous"] else names.get(r["respondentId"], "账号已不存在"),
                       "submittedAt": public(r["submittedAt"])} for r in rows[:limit]],
            "skip": skip, "limit": limit, "hasMore": len(rows)>limit}


@router.get("/api/question-versions/{vid}/distribution", response_model=DistributionOut)
def distribution(vid: str, request: Request, user=Depends(current_user),
                 surveyId: list[str] | None = Query(default=None, max_length=100),
                 skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    db = request.app.state.db
    _, content, _, base = statistical_context(db, vid, user, surveyId)
    if content["kind"] != "number":
        fail("只有数字题提供数值分布")
    rows = list(db.responses.aggregate(base + [{"$group": {"_id": "$answers.value", "answerCount": {"$sum": 1}}},
                {"$sort": {"_id": 1}}, {"$skip": skip}, {"$limit": limit+1}]))
    return {"items": [{"value": public(r["_id"]), "answerCount": r["answerCount"]} for r in rows[:limit]],
            "skip": skip, "limit": limit, "hasMore": len(rows)>limit}
