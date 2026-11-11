#!/usr/bin/env python3
"""CCD coordinator: planner + scheduler + integrator."""
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

if not os.environ.get("CCD_TOKEN"):
    raise SystemExit("Задайте переменную окружения CCD_TOKEN")
TOKEN = os.environ["CCD_TOKEN"]
DATA = Path(os.environ.get("CCD_DATA", "./data"))
(DATA / "repos").mkdir(parents=True, exist_ok=True)

WORKER_TIMEOUT = 90    # сек без heartbeat → воркер считается потерянным
MAX_ATTEMPTS = 3
PLAN_TIMEOUT = int(os.environ.get("CCD_PLAN_TIMEOUT", "900"))
CLAUDE_BIN = os.environ.get("CCD_CLAUDE", "claude")

db = sqlite3.connect(DATA / "ccd.db", check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
lock = threading.RLock()        # доступ к БД
merge_lock = threading.Lock()   # сериализация git-слияний

db.executescript("""
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, prompt TEXT, repo TEXT, base TEXT, test_cmd TEXT,
  integration TEXT, status TEXT, error TEXT, created REAL);
CREATE TABLE IF NOT EXISTS subtasks(
  id TEXT PRIMARY KEY, task_id TEXT, key TEXT, title TEXT, prompt TEXT,
  owns TEXT, deps TEXT, base_ref TEXT, branch TEXT, status TEXT,
  worker TEXT, attempts INTEGER DEFAULT 0, cost REAL DEFAULT 0,
  summary TEXT, resolves TEXT, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS workers(
  id TEXT PRIMARY KEY, name TEXT, slots INTEGER, labels TEXT, last_seen REAL);
""")


# ───────────────────────── утилиты ─────────────────────────
def sh(args, cwd=None, check=True, timeout=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{r.stderr.strip() or r.stdout.strip()}")
    return r


def rows(sql, *a):
    with lock:
        return [dict(r) for r in db.execute(sql, a).fetchall()]


def run(sql, *a):
    with lock:
        return db.execute(sql, a)


def get_task(tid):
    return rows("SELECT * FROM tasks WHERE id=?", tid)[0]


def get_subtask(sid):
    found = rows("SELECT * FROM subtasks WHERE id=?", sid)
    if not found:
        raise HTTPException(404, "subtask not found")
    return found[0]


def fail_task(tid, error):
    run("UPDATE tasks SET status='failed', error=? WHERE id=? AND status NOT IN ('done','failed')",
        error[:1500], tid)


# ───────────────────────── планировщик ─────────────────────────
PLAN_PROMPT = """Ты — архитектор-планировщик. Изучи репозиторий (только чтение) и разбей
задачу на независимые подзадачи для параллельной работы разных агентов.

Правила:
- у каждой подзадачи свой непересекающийся набор файлов/папок (owns, glob-шаблоны);
- общие файлы (конфиги, lock-файлы, общие типы) отдай ровно одной подзадаче;
- если подзадача зависит от результата другой — укажи deps (список ключей);
- 2–8 подзадач; если задачу нельзя разумно распараллелить — верни одну;
- key — короткий идентификатор из букв, цифр, "_" и "-" (например "A", "backend"); "VERIFY" зарезервирован;
- prompt подзадачи самодостаточен: цель, контекст, критерии готовности.

Ответь ТОЛЬКО JSON без пояснений и без markdown:
{"subtasks":[{"key":"A","title":"...","prompt":"...","owns":["src/x/**"],"deps":[]}]}

ЗАДАЧА:
"""

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def static_prefix(pattern: str) -> str:
    return re.split(r"[*?\[]", pattern)[0]


def patterns_overlap(a, b) -> bool:
    for p in a:
        for q in b:
            pp, qq = static_prefix(p), static_prefix(q)
            if pp.startswith(qq) or qq.startswith(pp):
                return True
    return False


def validate(subs):
    """Проверяет план планировщика. Бросает ValueError с понятным текстом."""

    def need(cond, msg):
        if not cond:
            raise ValueError(msg)

    need(isinstance(subs, list) and 1 <= len(subs) <= 12, "некорректное число подзадач")
    for s in subs:
        need(isinstance(s, dict), "подзадача должна быть объектом")
        for f in ("key", "title", "prompt"):
            need(isinstance(s.get(f), str) and s[f].strip(), f"у подзадачи нет поля {f}")
        need(KEY_RE.match(s["key"]) is not None, f"недопустимый key: {s['key']!r}")
        need(s["key"] != "VERIFY", "ключ VERIFY зарезервирован")
        need(isinstance(s.get("owns"), list) and s["owns"]
             and all(isinstance(p, str) and p for p in s["owns"]), f"{s['key']}: пустой owns")
        need(isinstance(s.get("deps", []), list), f"{s['key']}: deps должен быть списком")

    by = {s["key"]: s for s in subs}
    need(len(by) == len(subs), "дублирующиеся ключи подзадач")
    for s in subs:
        need(set(s.get("deps", [])) <= set(by), f"{s['key']}: неизвестная зависимость")

    # ациклический граф + предки
    anc = {}

    def visit(k, stack=()):
        need(k not in stack, "цикл в зависимостях")
        if k in anc:
            return anc[k]
        res = set()
        for d in by[k].get("deps", []):
            res |= {d} | visit(d, stack + (k,))
        anc[k] = res
        return res

    for k in by:
        visit(k)

    # независимые подзадачи не должны пересекаться по файлам
    keys = list(by)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a in anc[b] or b in anc[a]:
                continue
            need(not patterns_overlap(by[a]["owns"], by[b]["owns"]),
                 f"пересечение owns между {a} и {b}")


def add_subtask(task, key, title, prompt, owns, deps, base_ref=None, resolves=None):
    run("""INSERT INTO subtasks(id,task_id,key,title,prompt,owns,deps,base_ref,branch,status,resolves)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        f"{task['id']}:{key}", task["id"], key, title, prompt,
        json.dumps(owns), json.dumps(deps),
        base_ref or task["integration"], f"ccd/{task['id']}/{key}",
        "pending", resolves)


def extract_plan(output: str):
    text = json.loads(output)["result"]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])["subtasks"]


def plan_task(tid):
    try:
        task = get_task(tid)
        repo = DATA / "repos" / tid
        sh(["git", "clone", task["repo"], str(repo)])
        sh(["git", "checkout", "-B", task["integration"], f"origin/{task['base']}"], cwd=repo)
        sh(["git", "push", "-u", "origin", task["integration"]], cwd=repo)

        out = sh([CLAUDE_BIN, "-p", PLAN_PROMPT + task["prompt"],
                  "--output-format", "json", "--max-turns", "25",
                  "--allowedTools", "Read,Grep,Glob"], cwd=repo, timeout=PLAN_TIMEOUT).stdout
        subs = extract_plan(out)
        validate(subs)
        for s in subs:
            add_subtask(task, s["key"], s["title"], s["prompt"], s["owns"], s.get("deps", []))
        run("UPDATE tasks SET status='running' WHERE id=?", tid)
    except Exception as e:  # noqa: BLE001
        fail_task(tid, f"planning: {e}")


# ───────────────────────── интегратор ─────────────────────────
def integrate(sid):
    sub = rows("SELECT * FROM subtasks WHERE id=?", sid)[0]
    task = get_task(sub["task_id"])
    repo = DATA / "repos" / task["id"]
    try:
        with merge_lock:
            sh(["git", "fetch", "origin", "--prune"], cwd=repo)
            sh(["git", "checkout", task["integration"]], cwd=repo)
            sh(["git", "reset", "--hard", f"origin/{task['integration']}"], cwd=repo)
            r = sh(["git", "-c", "user.name=ccd", "-c", "user.email=ccd@local",
                    "merge", "--no-ff", "-m", f"merge {sub['key']}: {sub['title']}",
                    f"origin/{sub['branch']}"], cwd=repo, check=False)
            if r.returncode:
                sh(["git", "merge", "--abort"], cwd=repo, check=False)
                run("UPDATE subtasks SET status='conflict' WHERE id=?", sid)
                n = len(rows("SELECT id FROM subtasks WHERE task_id=? AND resolves=?",
                             task["id"], sub["key"])) + 1
                add_subtask(
                    task, f"{sub['key']}-fix{n}", f"Разрешить конфликт слияния {sub['key']}",
                    f"Ветка уже содержит работу подзадачи «{sub['title']}». Оркестратор начал "
                    f"слияние `origin/{task['integration']}` в эту ветку, и в некоторых файлах "
                    f"остались маркеры конфликта (<<<<<<<, =======, >>>>>>>). Разреши все "
                    f"конфликты, сохранив смысл обеих сторон, удали маркеры, затем запусти тесты "
                    f"и убедись, что всё проходит. Не делай commit и не запускай git merge — "
                    f"коммит сделает оркестратор.",
                    ["**"], [], base_ref=sub["branch"], resolves=sub["key"])
                return
            sh(["git", "push", "origin", task["integration"]], cwd=repo)

        # слияние разрешителя закрывает всю цепочку конфликтов, которую он решал
        run("UPDATE subtasks SET status='merged' WHERE id=?", sid)
        key = sub["resolves"]
        while key:
            run("UPDATE subtasks SET status='merged' WHERE task_id=? AND key=?", task["id"], key)
            parent = rows("SELECT resolves FROM subtasks WHERE task_id=? AND key=?", task["id"], key)
            key = parent[0]["resolves"] if parent else None
        advance(task["id"])
    except Exception as e:  # noqa: BLE001
        fail_task(task["id"], f"integrate {sid}: {e}")


def advance(tid):
    task = get_task(tid)
    if task["status"] != "running":
        return
    subs = rows("SELECT * FROM subtasks WHERE task_id=?", tid)
    verify = [s for s in subs if s["key"] == "VERIFY"]
    work = [s for s in subs if s["key"] != "VERIFY" and not s["resolves"]]
    if verify:
        if verify[0]["status"] == "merged":
            run("UPDATE tasks SET status='done' WHERE id=?", tid)
    elif work and all(s["status"] == "merged" for s in work):
        cmd = task["test_cmd"] or "тесты проекта"
        add_subtask(
            task, "VERIFY", "Финальная проверка интеграции",
            f"Все части слиты в интеграционную ветку. Запусти: {cmd}. "
            f"Если что-то падает — найди причину и внеси минимальные исправления. "
            f"Если всё проходит — ничего не меняй.",
            ["**"], [s["key"] for s in work])


# ───────────────────────── фоновые процессы ─────────────────────────
def reap_once(now=None):
    cutoff = (now or time.time()) - WORKER_TIMEOUT
    lost = """status='running' AND worker IN (SELECT id FROM workers WHERE last_seen<?)"""
    with lock:
        dead = [dict(r) for r in db.execute(
            f"SELECT id,task_id,key FROM subtasks WHERE {lost} AND attempts>=?",
            (cutoff, MAX_ATTEMPTS)).fetchall()]
        for s in dead:
            db.execute("UPDATE subtasks SET status='failed', summary='worker lost, attempts exhausted' "
                       "WHERE id=?", (s["id"],))
            fail_task(s["task_id"], f"{s['key']}: worker lost, attempts exhausted")
        db.execute(f"UPDATE subtasks SET status='pending', worker=NULL, summary='worker lost' "
                   f"WHERE {lost}", (cutoff,))


def reaper():
    while True:
        time.sleep(30)
        try:
            reap_once()
        except Exception as e:  # noqa: BLE001
            print("reaper error:", e)


def recover():
    """Восстановление после перезапуска координатора."""
    run("""UPDATE tasks SET status='failed', error='координатор перезапущен во время планирования'
           WHERE status='planning'""")
    for s in rows("SELECT id FROM subtasks WHERE status='completed'"):
        threading.Thread(target=integrate, args=(s["id"],), daemon=True).start()


@asynccontextmanager
async def lifespan(_app):
    recover()
    threading.Thread(target=reaper, daemon=True).start()
    yield


# ───────────────────────── API ─────────────────────────
app = FastAPI(title="ccd coordinator", lifespan=lifespan)


def auth(authorization: str = Header("")):
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "bad token")


class SubmitReq(BaseModel):
    prompt: str
    repo: str
    base: str = "main"
    test_cmd: str = ""


class RegisterReq(BaseModel):
    name: str
    slots: int = 2
    labels: list[str] = []


class HeartbeatReq(BaseModel):
    id: str
    load: float = 0


class ClaimReq(BaseModel):
    worker_id: str


class DoneReq(BaseModel):
    summary: str = ""
    cost: float = 0


class FailReq(BaseModel):
    error: str
    retryable: bool = True


@app.post("/tasks", dependencies=[Depends(auth)])
def submit(req: SubmitReq):
    tid = uuid.uuid4().hex[:8]
    run("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
        tid, req.prompt, req.repo, req.base, req.test_cmd,
        f"ccd/{tid}/integration", "planning", "", time.time())
    threading.Thread(target=plan_task, args=(tid,), daemon=True).start()
    return {"id": tid}


@app.get("/tasks", dependencies=[Depends(auth)])
def list_tasks():
    return rows("SELECT id,status,prompt,created FROM tasks ORDER BY created DESC LIMIT 50")


@app.get("/tasks/{tid}", dependencies=[Depends(auth)])
def task_state(tid: str):
    try:
        t = get_task(tid)
    except IndexError:
        raise HTTPException(404, "task not found")
    subs = rows("""SELECT key,title,status,worker,attempts,cost,branch,summary
                   FROM subtasks WHERE task_id=? ORDER BY rowid""", tid)
    return {"task": t, "subtasks": subs, "total_cost": sum(s["cost"] or 0 for s in subs)}


@app.post("/workers/register", dependencies=[Depends(auth)])
def register(req: RegisterReq):
    wid = uuid.uuid4().hex[:8]
    run("INSERT INTO workers VALUES(?,?,?,?,?)",
        wid, req.name, req.slots, json.dumps(req.labels), time.time())
    return {"id": wid}


@app.post("/workers/heartbeat", dependencies=[Depends(auth)])
def heartbeat(req: HeartbeatReq):
    run("UPDATE workers SET last_seen=? WHERE id=?", time.time(), req.id)
    return {"ok": True}


@app.get("/workers", dependencies=[Depends(auth)])
def list_workers():
    return rows("SELECT id,name,slots,labels,last_seen FROM workers")


@app.post("/claim", dependencies=[Depends(auth)])
def claim(req: ClaimReq):
    with lock:
        run("UPDATE workers SET last_seen=? WHERE id=?", time.time(), req.worker_id)
        merged = {(r["task_id"], r["key"])
                  for r in rows("SELECT task_id,key FROM subtasks WHERE status='merged'")}
        pending = rows("""SELECT s.* FROM subtasks s JOIN tasks t ON t.id=s.task_id
                          WHERE s.status='pending' AND t.status='running' ORDER BY s.rowid""")
        for s in pending:
            if all((s["task_id"], d) in merged for d in json.loads(s["deps"])):
                run("""UPDATE subtasks SET status='running', worker=?, attempts=attempts+1, started=?
                       WHERE id=?""", req.worker_id, time.time(), s["id"])
                task = get_task(s["task_id"])
                s["owns"] = json.loads(s["owns"])
                s["deps"] = json.loads(s["deps"])
                s["last_error"] = s["summary"] if s["attempts"] > 0 else ""
                return {"subtask": s, "task": task}
    return Response(status_code=204)


@app.post("/subtasks/{sid}/complete", dependencies=[Depends(auth)])
def complete(sid: str, body: DoneReq):
    with lock:
        if get_subtask(sid)["status"] != "running":
            return {"ok": False, "reason": "not running"}   # дубль или устаревший воркер
        run("UPDATE subtasks SET status='completed', summary=?, cost=cost+?, finished=? WHERE id=?",
            body.summary, body.cost, time.time(), sid)
    threading.Thread(target=integrate, args=(sid,), daemon=True).start()
    return {"ok": True}


@app.post("/subtasks/{sid}/fail", dependencies=[Depends(auth)])
def fail(sid: str, body: FailReq):
    with lock:
        s = get_subtask(sid)
        if s["status"] != "running":
            return {"ok": False, "reason": "not running"}
        if body.retryable and s["attempts"] < MAX_ATTEMPTS:
            run("UPDATE subtasks SET status='pending', worker=NULL, summary=? WHERE id=?",
                body.error, sid)
        else:
            run("UPDATE subtasks SET status='failed', summary=? WHERE id=?", body.error, sid)
            fail_task(s["task_id"], f"{s['key']}: {body.error[:500]}")
    return {"ok": True}
