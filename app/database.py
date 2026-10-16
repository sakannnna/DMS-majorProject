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


def initialize(db):
    schemas = {
        "users": ({"usernameKey": "string", "username": "string", "passwordHash": "string", "createdAt": "date"}, []),
        "surveys": ({"ownerId": "objectId", "token": "string", "title": "string", "questions": "array", "status": "string",
                     "editRevision": "int", "definitionVersion": "int", "allowAnonymous": "bool", "allowMultiple": "bool",
                     "createdAt": "date", "updatedAt": "date"}, []),
        "responses": ({"surveyId": "objectId", "respondentId": "objectId", "answers": "array", "anonymous": "bool",
                       "submissionKey": "string", "payloadHash": "string", "definitionVersion": "int", "submittedAt": "date"}, []),
        "sessions": ({"tokenHash": "string", "userId": "objectId", "createdAt": "date", "expiresAt": "date"}, []),
    }
    existing = set(db.list_collection_names())
    # Preflight every collection before any collMod: old code must not downgrade a newer schema.
    for name in schemas.keys() & existing:
        options = db[name].options()
        version_rule = options.get("validator", {}).get("$jsonSchema", {}).get("properties", {}).get("schemaVersion", {})
        if version_rule.get("enum", [1]) != [1] or db[name].find_one({"schemaVersion": {"$ne": 1}}, {"_id": 1}):
            raise RuntimeError(f"Unsupported schema in {name}; use the matching application or an explicit migration")
    for name, (fields, _) in schemas.items():
        props = {k: {"bsonType": t} for k, t in fields.items()}
        props["schemaVersion"] = {"bsonType": "int", "enum": [1]}
        if name == "surveys":
            props["status"]["enum"] = ["draft", "published", "closed"]
            props["deadline"] = {"bsonType": ["date", "null"]}
            props["questions"]["maxItems"] = 100
        if name == "responses":
            props["answers"]["maxItems"] = 100
        validator = {"$jsonSchema": {"bsonType": "object", "required": [*fields, "schemaVersion"], "properties": props}}
        if name not in existing:
            db.create_collection(name, validator=validator)
        else:
            # Idempotent baseline validator; future versions require an explicit migration.
            db.command("collMod", name, validator=validator, validationLevel="strict")
    db.users.create_index("usernameKey", unique=True)
    db.surveys.create_index("token", unique=True)
    db.surveys.create_index([("ownerId", 1), ("createdAt", -1)])
    db.sessions.create_index("tokenHash", unique=True)
    db.sessions.create_index("expiresAt", expireAfterSeconds=0)
    db.responses.create_index([("surveyId", 1), ("submittedAt", -1)])
    db.responses.create_index([("surveyId", 1), ("respondentId", 1), ("submissionKey", 1)], unique=True)
    db.responses.create_index([("surveyId", 1), ("singleSubmissionKey", 1)], unique=True,
                              partialFilterExpression={"singleSubmissionKey": {"$exists": True}})
