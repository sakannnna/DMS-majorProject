"""整卷保存与单个题目操作共用来源校验及修订号检查，防止并发覆盖。"""
import copy

from pymongo import ReturnDocument
from pydantic import ValidationError

from .database import now, public
from .logic import fail, prepare_survey
from .models import QuestionContent, SurveyInput
from .reusable import content_of, fingerprint, prepare_content, readable_version


DEFINITION_FIELDS = ("title", "description", "deadline", "allowAnonymous", "allowMultiple", "questions")


def definition(s):
    return {k: public(copy.deepcopy(s[k])) for k in DEFINITION_FIELDS}


def normalize_positions(db, survey, user, data, revision, key):
    previous = {q["id"]: q for q in survey["questions"]}
    id_map = {}
    for q in data["questions"]:
        old = previous.get(q["id"])
        source, version = q.get("sourceQuestionId"), q.get("sourceVersionId")
        if bool(source) != bool(version):
            fail("题目来源和版本必须同时提供")
        if old and old.get("sourceVersionId"):
            if source != old["sourceQuestionId"] or not version:
                fail("已有可复用位置不能移除来源或换成另一系列")
            # 已保存快照不重新依赖共享权限；换入新版本时才重新授权并读取内容。
            if version == old["sourceVersionId"]:
                supplied = prepare_content(QuestionContent(**content_of(q)))
                if fingerprint(supplied) != fingerprint(content_of(old)):
                    fail("版本快照不可编辑，请先保存新版本并主动换版")
                q.update(content_of(old))
            else:
                v = readable_version(db, version, user, selecting=True)
                if str(v["questionId"]) != source:
                    fail("目标版本不属于当前题目系列")
                q.update(content_of(v["content"]))
        elif version:
            if old:
                fail("普通题导出不自动绑定原位置，请新增可复用位置")
            if not key:
                fail("新增可复用位置需要operationKey")
            v = readable_version(db, version, user, selecting=True)
            if str(v["questionId"]) != source:
                fail("版本不属于来源题目")
            temporary = q["id"]
            # 同一版本的各次选入使用独立位置；同一操作重试仍生成相同标识。
            q["id"] = "r" + fingerprint([str(survey["_id"]), revision, key, temporary])[:48]
            if temporary in id_map:
                fail("批内临时位置标识重复")
            id_map[temporary] = q["id"]
            q.update(content_of(v["content"]))
    for q in data["questions"]:
        for rule in q.get("jumpRules", []):
            rule["target"] = id_map.get(rule["target"], rule["target"])
    try:
        model = SurveyInput(**public(data))
    except ValidationError:
        fail("题目数量、标识或规则超出支持范围")
    return prepare_survey(model), id_map


def replay(s, revision, key, hashed):
    receipt = s.get("lastMutation")
    if key and receipt and receipt["operationKey"] == key and receipt["baseRevision"] == revision:
        if receipt["requestHash"] != hashed:
            fail("同一操作键不能用于不同输入", 409)
        if s["editRevision"] == receipt["resultRevision"]:
            return public({**s, "idMap": receipt["idMap"]})
    return None


def save_definition(db, survey, user, revision, key, signature, build):
    hashed = fingerprint(signature)
    result = replay(survey, revision, key, hashed)
    if result:
        return result
    if survey["status"] != "draft" or survey["editRevision"] != revision:
        fail("问卷已变化或定义已冻结，请刷新", 409)
    prepared, id_map = normalize_positions(db, survey, user, build(), revision, key)
    changes = {**prepared, "schemaVersion": 2, "updatedAt": now()}
    update = {"$set": changes, "$inc": {"editRevision": 1}}
    if key:
        changes["lastMutation"] = {"operationKey": key, "baseRevision": revision, "requestHash": hashed,
                                   "resultRevision": revision + 1, "idMap": id_map}
    else:
        update["$unset"] = {"lastMutation": ""}
    stored = db.surveys.find_one_and_update(
        {"_id": survey["_id"], "ownerId": user["_id"], "editRevision": revision, "status": "draft"},
        update, return_document=ReturnDocument.AFTER)
    if not stored:
        latest = db.surveys.find_one({"_id": survey["_id"], "ownerId": user["_id"]})
        result = replay(latest, revision, key, hashed) if latest else None
        if result:
            return result
        fail("内容已变化，请刷新后重试", 409)
    return public({**stored, "idMap": id_map})
