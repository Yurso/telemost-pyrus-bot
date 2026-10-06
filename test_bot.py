import os
os.environ.update(YANDEX_BOT_TOKEN="x", PYRUS_LOGIN="x", PYRUS_SECURITY_KEY="x")
import bot

u = {"from": {"login": "me@corp.ru"}, "chat": {"type": "private", "id": "1"}, "text": "",
     "forwarded_messages": [{"from": {"login": "ivan@corp.ru", "display_name": "Иван"},
                             "text": "\n Не работает принтер на 3 этаже\nсрочно"}]}
t = bot.build_task(u)
assert t["subject"] == "Не работает принтер на 3 этаже", t
assert "Инициатор: Иван (ivan@corp.ru)" in t["text"] and t["participants"] == [{"email": "ivan@corp.ru"}]
assert bot.build_task({**u, "forwarded_messages": []}) is None
assert len(bot.make_subject("a" * 500)) == bot.SUBJECT_LEN
bot.PYRUS_FORM_ID = "42"
f = bot.build_task(u)
assert f["form_id"] == 42 and {"name": "Инициатор", "value": {"email": "ivan@corp.ru"}} in f["fields"]

bot.PYRUS_FORM_ID = None
# attachments: file + biggest image size, attachments-only message still makes a task
a = {"from": {"login": "me@corp.ru"}, "chat": {"type": "private", "id": "1"},
     "forwarded_messages": [{"from": {"login": "ivan@corp.ru"}, "file": {"id": "F1", "name": "лог.txt", "size": 3},
                             "images": [[{"file_id": "s", "width": 100, "height": 1},
                                         {"file_id": "L", "width": 900, "height": 1, "name": "scr.png"}]]}]}
assert bot.list_files(a) == [("F1", "лог.txt"), ("L", "scr.png")]
assert bot.build_task(a)["subject"] == "Обращение из Телемоста"

# full handle(): files uploaded, guids attached, reply sent
calls = []
def fake_http(method, url, body=None, headers=None, raw=False):
    calls.append((url, body))
    if "getFile" in url: return b"DATA"
    if "files/upload" in url:
        assert b"DATA" in body and "multipart/form-data" in headers["Content-Type"]
        return {"guid": "g%d" % len(calls)}
    if url.endswith("tasks"): return {"task": {"id": 7}}
    return {}
bot.http = fake_http
p = bot.Pyrus(); p.token, p.api_url = "t", "https://api/"
bot.handle(a, p)
task = next(b for u, b in calls if u.endswith("tasks"))
assert task["attachments"] == ["g2", "g4"], task
assert "#7" in calls[-1][1]["text"]
print("ok")
