import os
import re
from datetime import datetime, timezone
from decimal import Decimal

from bson import Decimal128, ObjectId
from pymongo import MongoClient


def now():
    return datetime.now(timezone.utc)


def public(value):
    if isinstance(value, dict):
        return {"id" if k == "_id" else k: public(v) for k, v in value.items()}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def connect():
    name = os.getenv("MONGODB_DB", "survey_course")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError("MONGODB_DB must contain only letters, numbers and underscores")
    client = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27019"),
                         serverSelectionTimeoutMS=4000, tz_aware=True)
    client.admin.command("ping")
    return client, client[name]


# 升级写入前统一检查所有集合的校验规则，避免检查到一半就修改数据库。
SCHEMAS = {
    "users": {"usernameKey": "string", "username": "string", "passwordHash": "string", "createdAt": "date"},
    "surveys": {"ownerId": "objectId", "token": "string", "title": "string", "questions": "array", "status": "string",
                "editRevision": "int", "definitionVersion": "int", "allowAnonymous": "bool", "allowMultiple": "bool",
                "createdAt": "date", "updatedAt": "date"},
    "responses": {"surveyId": "objectId", "respondentId": "objectId", "answers": "array", "anonymous": "bool",
                  "submissionKey": "string", "payloadHash": "string", "definitionVersion": "int", "submittedAt": "date"},
    "sessions": {"tokenHash": "string", "userId": "objectId", "createdAt": "date", "expiresAt": "date"},
    "reusableQuestions": {"ownerId": "objectId", "name": "string", "archived": "bool", "editRevision": "int",
                          "nextVersionNo": "int", "creationKey": "string", "requestHash": "string",
                          "createdAt": "date", "updatedAt": "date"},
    "questionShares": {"versionId": "objectId", "recipientId": "objectId", "active": "bool", "editRevision": "int", "createdAt": "date"},
    "questionBanks": {"ownerId": "objectId", "name": "string", "archived": "bool", "editRevision": "int", "createdAt": "date", "updatedAt": "date"},
    "questionBankItems": {"bankId": "objectId", "questionId": "objectId", "selectedVersionId": "objectId", "editRevision": "int", "createdAt": "date", "updatedAt": "date"},
    "questionVersions": {"questionId": "objectId", "versionNo": "int", "content": "object", "creationKey": "string",
                         "requestHash": "string", "createdAt": "date"},
}


def versions_for(name):
    return [1, 2] if name == "surveys" else [2] if name not in ("users", "sessions", "responses") else [1]


def preflight(db, upgrading=False):
    existing = set(db.list_collection_names())
    for name in SCHEMAS.keys() & existing:
        rule = db[name].options().get("validator", {}).get("$jsonSchema", {}).get("properties", {}).get("schemaVersion", {})
        allowed = versions_for(name)
        enums = rule.get("enum", [1])
        expected_validator = validator_for(name)
        expected_validator["$jsonSchema"]["properties"]["schemaVersion"]["enum"] = enums
        supported = [allowed] + ([[1]] if upgrading and name == "surveys" else [])
        if db[name].options().get("validator") != expected_validator or enums not in supported or db[name].find_one({"schemaVersion": {"$nin": allowed}}, {"_id": 1}):
            raise RuntimeError(f"Unsupported schema in {name}; explicit migration required (旧库请先运行 upgrade-db.py)")
    return existing


def validator_for(name):
    fields = SCHEMAS[name]
    props = {k: {"bsonType": t} for k, t in fields.items()}
    props["schemaVersion"] = {"bsonType": "int", "enum": versions_for(name)}
    if name == "surveys":
        props["status"]["enum"] = ["draft", "published", "closed"]
        props["deadline"] = {"bsonType": ["date", "null"]}
        props["questions"]["maxItems"] = 100
    if name == "responses":
        props["answers"]["maxItems"] = 100
    return {"$jsonSchema": {"bsonType": "object", "required": [*fields, "schemaVersion"], "properties": props}}


def install(db, existing):
    for name in SCHEMAS:
        if name not in existing:
            db.create_collection(name, validator=validator_for(name))
        else:
            db.command("collMod", name, validator=validator_for(name), validationLevel="strict")
    db.users.create_index("usernameKey", unique=True)
    db.surveys.create_index("token", unique=True)
    db.surveys.create_index([("ownerId", 1), ("createdAt", -1)])
    db.sessions.create_index("tokenHash", unique=True)
    db.sessions.create_index("expiresAt", expireAfterSeconds=0)
    db.responses.create_index([("surveyId", 1), ("submittedAt", -1), ("_id", -1)])
    # 唯一索引分别约束重复请求和限填一次；允许多次填写的答卷不受后者限制。
    db.responses.create_index([("surveyId", 1), ("respondentId", 1), ("submissionKey", 1)], unique=True)
    db.responses.create_index([("surveyId", 1), ("singleSubmissionKey", 1)], unique=True,
                              partialFilterExpression={"singleSubmissionKey": {"$exists": True}})
    db.reusableQuestions.create_index([("ownerId", 1), ("archived", 1), ("updatedAt", -1), ("_id", -1)])
    db.reusableQuestions.create_index([("ownerId", 1), ("creationKey", 1)], unique=True)
    db.questionVersions.create_index([("questionId", 1), ("versionNo", 1)], unique=True)
    db.questionVersions.create_index([("questionId", 1), ("creationKey", 1)], unique=True)
    db.questionVersions.create_index([("parentVersionId", 1), ("_id", 1)])
    db.surveys.create_index([("ownerId", 1), ("questions.sourceVersionId", 1), ("_id", 1)])
    db.questionShares.create_index([("versionId", 1), ("recipientId", 1)], unique=True)
    db.questionShares.create_index([("recipientId", 1), ("active", 1), ("versionId", 1)])
    db.questionBanks.create_index([("ownerId", 1), ("archived", 1), ("updatedAt", -1), ("_id", -1)])
    db.questionBankItems.create_index([("bankId", 1), ("questionId", 1)], unique=True)
    db.questionBankItems.create_index([("bankId", 1), ("createdAt", -1), ("_id", -1)])
    # 先建好替代索引，再删除已知冗余索引，避免查询失去索引支持。
    for name, spec in db.responses.index_information().items():
        if spec["key"] == [("surveyId", 1), ("submittedAt", -1)] and not spec.get("unique"):
            db.responses.drop_index(name)


def initialize(db):
    # 旧库必须先备份并显式升级，不能通过重启应用静默改写集合结构。
    existing = preflight(db)
    if existing and not SCHEMAS.keys() <= existing:
        raise RuntimeError("Incomplete migration; finish upgrade-db.py before starting the app")
    install(db, existing)


def upgrade(db):
    existing = preflight(db, upgrading=True)
    install(db, existing)
