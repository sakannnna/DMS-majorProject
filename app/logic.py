"""Shared question validation and deterministic forward-only traversal."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from bson import BSON, Decimal128
from fastapi import HTTPException


def fail(message, status=422):
    raise HTTPException(status, message)


def number(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError()
        Decimal128(result)
        return result
    except (ValueError, InvalidOperation, ArithmeticError):
        fail("数字必须有限且在 Decimal128 支持范围内")


def deadline(value):
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            fail("截止时间必须带时区")
        return parsed.astimezone(timezone.utc)
    except ValueError:
        fail("截止时间格式错误")


def decimal_value(value):
    return value.to_decimal() if isinstance(value, Decimal128) else number(value)


def prepare_survey(model):
    data = model.model_dump(exclude={"editRevision", "operationKey"})
    data["title"] = data["title"].strip()
    if not data["title"]:
        fail("问卷标题不能为空")
    data["deadline"] = deadline(data["deadline"])
    for q in data["questions"]:
        if not q.get("sourceQuestionId") and not q.get("sourceVersionId"):
            q.pop("sourceQuestionId", None)
            q.pop("sourceVersionId", None)
        q["title"] = q["title"].strip()
        q["options"] = [{**o, "label": o["label"].strip()} for o in q["options"]]
        q["validation"] = {k: Decimal128(number(x)) if isinstance(x, Decimal) else x for k, x in q["validation"].items()}
    validate_definition(data)
    if len(BSON.encode(data)) > 2_000_000:
        fail("问卷定义超过 2 MB 限制")
    return data


def validate_definition(survey, publishing=False):
    questions = survey["questions"]
    ids = [q["id"] for q in questions]
    if len(set(ids)) != len(ids) or "END" in ids:
        fail("题目标识重复或使用了保留标识 END")
    if publishing and not questions:
        fail("至少添加一道题后才能发布")
    for i, q in enumerate(questions):
        if not q["title"]:
            fail("题目标题不能为空")
        kind, v, options = q["kind"], q["validation"], q["options"]
        option_ids = [o["id"] for o in options]
        if len(set(option_ids)) != len(option_ids) or any(not o["label"] for o in options):
            fail("选项标识重复或选项为空")
        if kind in ("single", "multiple"):
            if len(options) < 2:
                fail("选择题至少需要两个选项")
        elif options:
            fail("填空题不能配置选项")
        allowed = {"multiple": {"minChoices", "maxChoices"}, "text": {"minLength", "maxLength"},
                   "number": {"minimum", "maximum", "integer"}, "single": set()}[kind]
        if any(k not in allowed and value is not None and not (k == "integer" and value is False) for k, value in v.items()):
            fail("校验配置与题型不匹配")
        for low, high in [("minChoices", "maxChoices"), ("minLength", "maxLength"), ("minimum", "maximum")]:
            lo, hi = v[low], v[high]
            if low == "minimum":
                lo = decimal_value(lo) if lo is not None else None
                hi = decimal_value(hi) if hi is not None else None
            if lo is not None and hi is not None and lo > hi:
                fail("校验最小值不能超过最大值")
        if kind == "multiple":
            if any(v[k] is not None and v[k] > len(options) for k in ("minChoices", "maxChoices")):
                fail("多选数量不能超过选项数")
            if q["required"] and v["maxChoices"] == 0:
                fail("必答多选题不能限制为零项")
        if q["jumpRules"] and kind == "text":
            fail("文本题暂不支持跳转条件")
        for rule in q["jumpRules"]:
            target = rule["target"]
            if target != "END" and (target not in ids or ids.index(target) <= i):
                fail("跳转目标必须是后面的题目或 END")
            for c in rule["conditions"]:
                op, val = c["op"], c["value"]
                if kind == "single":
                    if op != "eq" or not isinstance(val, str) or val not in option_ids:
                        fail("单选跳转须使用 eq 和本题选项")
                elif kind == "multiple":
                    if op not in ("any", "all") or not isinstance(val, list) or not val or len(set(val)) != len(val) or any(x not in option_ids for x in val):
                        fail("多选跳转须使用 any/all 和非空本题选项列表")
                elif kind == "number":
                    if op not in ("eq", "ne", "gt", "gte", "lt", "lte") or not isinstance(val, str):
                        fail("数字跳转条件格式错误")
                    number(val)


def normalize(q, value):
    kind, v = q["kind"], q["validation"]
    if value is None or value == [] or isinstance(value, str) and not value.strip():
        if q["required"]:
            fail(f"{q['title']}：此题必答")
        return None
    if kind in ("single", "multiple"):
        allowed = {o["id"] for o in q["options"]}
        if kind == "single":
            if not isinstance(value, str) or value not in allowed:
                fail(f"{q['title']}：请选择合法选项")
            return value
        if not isinstance(value, list) or len(set(value)) != len(value) or any(x not in allowed for x in value):
            fail(f"{q['title']}：多选存在重复或非法选项")
        if v["minChoices"] is not None and len(value) < v["minChoices"] or v["maxChoices"] is not None and len(value) > v["maxChoices"]:
            fail(f"{q['title']}：选择数量不符合限制")
        return sorted(value)
    if not isinstance(value, str):
        fail(f"{q['title']}：填写格式错误")
    value = value.strip()
    if kind == "text":
        if len(value) > 5000 or v["minLength"] is not None and len(value) < v["minLength"] or v["maxLength"] is not None and len(value) > v["maxLength"]:
            fail(f"{q['title']}：文本长度不符合限制")
        return value
    result = number(value)
    if v["integer"] and result != result.to_integral_value():
        fail(f"{q['title']}：必须为整数")
    if v["minimum"] is not None and result < decimal_value(v["minimum"]) or v["maximum"] is not None and result > decimal_value(v["maximum"]):
        fail(f"{q['title']}：数字超出范围")
    return Decimal128(result)


def matches(conditions, value):
    if value is None:
        return False
    for c in conditions:
        op, other, val = c["op"], c["value"], value
        if isinstance(value, Decimal128):
            val, other = value.to_decimal(), number(other)
        if op == "any":
            ok = bool(set(val) & set(other))
        elif op == "all":
            ok = set(other).issubset(val)
        else:
            ok = {"eq": lambda: val == other, "ne": lambda: val != other,
                  "gt": lambda: val > other, "gte": lambda: val >= other,
                  "lt": lambda: val < other, "lte": lambda: val <= other}[op]()
        if not ok:
            return False
    return True


def walk(survey, answers, complete=False):
    questions = survey["questions"]
    mapping = {a.questionId: a.value for a in answers}
    if len(mapping) != len(answers):
        fail("同一道题不能重复提交答案")
    if any(k not in {q["id"] for q in questions} for k in mapping):
        fail("答案含未知题目")
    path, normalized, i = [], [], 0
    while i < len(questions):
        q = questions[i]
        path.append(q["id"])
        if q["id"] not in mapping:
            if complete:
                fail(f"{q['title']}：尚未确认回答")
            if set(mapping) - set(path):
                fail("答案不在当前有效路径内")
            return {"path": path, "nextQuestionId": q["id"], "ready": False}, normalized
        value = normalize(q, mapping[q["id"]])
        if value is not None:
            normalized.append({"questionId": q["id"], "value": value})
        target = next((r["target"] for r in q["jumpRules"] if matches(r["conditions"], value)), None)
        if target == "END":
            break
        i = next(j for j, candidate in enumerate(questions) if candidate["id"] == target) if target else i + 1
    if set(mapping) - set(path):
        fail("答案含被跳过的题目，请重新确认填写路径")
    return {"path": path, "nextQuestionId": None, "ready": True}, normalized
