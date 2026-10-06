"""Telemost (Yandex Messenger Bot API) -> Pyrus: forwarded message becomes a Pyrus task."""
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

YA_API = "https://botapi.messenger.yandex.net/bot/v1/messages"
YA_TOKEN = os.environ["YANDEX_BOT_TOKEN"]
PYRUS_LOGIN = os.environ["PYRUS_LOGIN"]
PYRUS_KEY = os.environ["PYRUS_SECURITY_KEY"]
PYRUS_FORM_ID = os.getenv("PYRUS_FORM_ID")  # empty -> simple task
F_SUBJECT = os.getenv("PYRUS_FIELD_SUBJECT", "Тема")
F_TEXT = os.getenv("PYRUS_FIELD_TEXT", "Описание")
F_INITIATOR = os.getenv("PYRUS_FIELD_INITIATOR", "Инициатор")
ALLOWED = {x.strip().lower() for x in os.getenv("ALLOWED_LOGINS", "").split(",") if x.strip()}
SUBJECT_LEN = 100

log = logging.getLogger("bot")


def http(method, url, body=None, headers=None, raw=False):
    """body: dict -> JSON, bytes -> sent as is (set Content-Type in headers). raw=True returns bytes."""
    if isinstance(body, bytes):
        data, h = body, headers or {}
    else:
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read() if raw else json.load(r)


def ya(method, path, body=None, raw=False):
    return http(method, f"{YA_API}/{path}", body, {"Authorization": f"OAuth {YA_TOKEN}"}, raw)


def ya_download(file_id):
    return ya("GET", "getFile/?" + urllib.parse.urlencode({"file_id": file_id}), raw=True)


def list_files(update):
    """(file_id, name) for files and images in the update and its forwarded messages."""
    out = []
    for m in [update, *(update.get("forwarded_messages") or [])]:
        if m.get("file"):
            out.append((m["file"]["id"], m["file"]["name"]))
        for sizes in m.get("images") or []:  # each picture comes in several sizes, take the biggest
            if sizes:
                img = max(sizes, key=lambda i: i.get("width", 0))
                out.append((img["file_id"], img.get("name") or f"image_{len(out) + 1}.jpg"))
    return out


class Pyrus:
    token = api_url = None

    def auth(self):
        r = http("POST", "https://accounts.pyrus.com/api/v4/auth", {"login": PYRUS_LOGIN, "security_key": PYRUS_KEY})
        self.token, self.api_url = r["access_token"], r.get("api_url", "https://api.pyrus.com/v4/")

    def call(self, path, body, headers=None):
        if not self.token:
            self.auth()
        for attempt in (1, 2):
            try:
                return http("POST", f"{self.api_url}{path}", body, {"Authorization": f"Bearer {self.token}", **(headers or {})})
            except urllib.error.HTTPError as e:
                if e.code != 401 or attempt == 2:
                    raise
                self.auth()  # token expired

    def create_task(self, task):
        return self.call("tasks", task)["task"]

    def upload(self, name, data):
        boundary = uuid.uuid4().hex
        fname = urllib.parse.quote(name)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"; '
                f"filename*=UTF-8''{fname}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
            + data + f"\r\n--{boundary}--\r\n".encode()
        return self.call("files/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})["guid"]


def make_subject(text):
    line = next((l.strip() for l in text.splitlines() if l.strip()), "Обращение из Телемоста")
    return line if len(line) <= SUBJECT_LEN else line[:SUBJECT_LEN - 1].rstrip() + "…"


def build_task(update):
    """Returns Pyrus task payload from an update with forwarded messages, or None."""
    fwd = update.get("forwarded_messages") or []
    if not fwd:
        return None
    sender = fwd[0].get("from") or {}
    login, name = sender.get("login", ""), sender.get("display_name") or sender.get("login", "?")
    text = "\n\n".join(m["text"] for m in fwd if m.get("text"))
    if update.get("text"):  # my own comment added while forwarding
        text = f"{update['text']}\n\n---\n{text}"
    if not text.strip() and not list_files(update):
        return None
    subject = make_subject("\n\n".join(m["text"] for m in fwd if m.get("text")) or text)
    body = f"{text}\n\nИнициатор: {name} ({login})\nПереслал: {update['from'].get('login')}"
    if PYRUS_FORM_ID:
        fields = [{"name": F_SUBJECT, "value": subject}, {"name": F_TEXT, "value": body}]
        if login:
            fields.append({"name": F_INITIATOR, "value": {"email": login}})
        return {"form_id": int(PYRUS_FORM_ID), "fields": fields}
    task = {"subject": subject, "text": body}
    if login:
        task["participants"] = [{"email": login}]
    return task


def reply(update, text):
    chat = update["chat"]
    target = {"chat_id": chat["id"]} if chat.get("type") != "private" else {"login": update["from"]["login"]}
    ya("POST", "sendText/", {**target, "text": text})


def handle(update, pyrus):
    sender = (update.get("from") or {}).get("login", "").lower()
    if ALLOWED and sender not in ALLOWED:
        return log.info("ignored message from %s", sender)
    task = build_task(update)
    if task is None:
        return reply(update, "Перешлите мне сообщение — я создам по нему заявку в Pyrus.")
    failed = []
    for file_id, name in list_files(update):
        try:
            task.setdefault("attachments", []).append(pyrus.upload(name, ya_download(file_id)))
        except Exception:
            log.exception("attachment %s failed", name)
            failed.append(name)
    try:
        created = pyrus.create_task(task)
    except urllib.error.HTTPError as e:
        # initiator may be unknown to Pyrus -> retry without it, it's still in the text
        fields = task.get("fields", [])
        no_init = [f for f in fields if f["name"] != F_INITIATOR]
        if e.code != 400 or not (task.pop("participants", None) or len(no_init) < len(fields)):
            raise
        log.warning("pyrus 400, retrying without initiator: %s", e.read().decode(errors="replace"))
        if fields:
            task["fields"] = no_init
        created = pyrus.create_task(task)
    msg = f"Заявка #{created['id']} создана: https://pyrus.com/t#id{created['id']}"
    if failed:
        msg += "\nНе удалось приложить: " + ", ".join(failed)
    reply(update, msg)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pyrus, offset = Pyrus(), 0
    log.info("bot started")
    while True:
        try:
            updates = ya("GET", f"getUpdates/?limit=100&offset={offset}").get("updates", [])
        except Exception:
            log.exception("getUpdates failed")
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle(u, pyrus)
            except Exception:
                log.exception("failed to handle update %s", u.get("update_id"))
                try:
                    reply(u, "Не удалось создать заявку, смотрите логи бота.")
                except Exception:
                    pass
        if not updates:
            time.sleep(1)  # ponytail: polling; switch to webhook if latency matters


if __name__ == "__main__":
    main()
