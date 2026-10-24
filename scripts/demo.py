"""通过正式接口创建可复现示例，不覆盖已有问卷。"""
import getpass
import os

import httpx


def main():
    base = os.getenv("SURVEY_BASE_URL", "http://127.0.0.1:8009")
    name = input("演示账号用户名 [课堂演示]: ").strip() or "课堂演示"
    password = getpass.getpass("该账号密码（首次使用会注册，至少8位）: ")
    with httpx.Client(base_url=base) as client:
        client.headers["x-csrf-token"] = client.get("/api/session").json()["csrf"]
        credentials = {"username": name, "password": password}
        login = client.post("/api/login", json=credentials)
        if login.status_code != 200:
            registered = client.post("/api/register", json=credentials)
            if registered.status_code != 201:
                raise SystemExit("注册或登录失败，请核对已有账号密码和用户名要求。")
            login = client.post("/api/login", json=credentials)
            login.raise_for_status()
        title = "课程学习体验问卷 示例"
        existing = next((s for s in client.get("/api/surveys?limit=100").json() if s["title"] == title), None)
        if existing:
            print("发现已有同名示例，未覆盖：", base + "/survey/" + existing["token"])
            return
        body = {"title": title, "description": "可复现的课程演示：四种输入、三类跳转、匿名与重复填写。", "allowAnonymous": True, "allowMultiple": True,
                "questions": [
                    {"id": "q1", "title": "是否继续？", "kind": "single", "options": [{"id": "yes", "label": "继续"}, {"id": "no", "label": "暂不填写"}],
                     "jumpRules": [{"conditions": [{"op": "eq", "value": "no"}], "target": "END"}]},
                    {"id": "q2", "title": "你喜欢哪些学习方式？", "kind": "multiple", "options": [{"id": "video", "label": "视频"}, {"id": "book", "label": "教材"}, {"id": "lab", "label": "实验"}],
                     "validation": {"minChoices": 1, "maxChoices": 2}, "jumpRules": [{"conditions": [{"op": "any", "value": ["lab"]}], "target": "q4"}]},
                    {"id": "q3", "title": "你最想了解什么？", "kind": "text", "validation": {"minLength": 2, "maxLength": 100}},
                    {"id": "q4", "title": "每周学习小时数", "kind": "number", "validation": {"minimum": "0", "maximum": "40", "integer": True},
                     "jumpRules": [{"conditions": [{"op": "gte", "value": "20"}], "target": "END"}]},
                    {"id": "q5", "title": "其他建议", "kind": "text", "required": False, "validation": {"maxLength": 100}}
                ]}
        response = client.post("/api/surveys", json=body)
        response.raise_for_status()
        survey = response.json()
        published = client.post(f"/api/surveys/{survey['id']}/publish", json={"editRevision": survey["editRevision"]})
        published.raise_for_status()
        print("示例链接：", base + "/survey/" + survey["token"])


if __name__ == "__main__":
    main()
