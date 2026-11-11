#!/usr/bin/env python3
"""CCD worker: берёт подзадачи, запускает Claude Code в git worktree."""
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil

DEFAULT_TOOLS = ("Read,Edit,Write,Grep,Glob,Bash(npm test:*),Bash(npm run:*),"
                 "Bash(pytest:*),Bash(git diff:*),Bash(git status:*)")

git_lock = threading.Lock()
WID = None
CFG = {}
WORK = Path(".")
api = None


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{r.stderr.strip() or r.stdout.strip()}")
    return r


class JobError(Exception):
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


# ───────────────────────── владение файлами ─────────────────────────
def glob_to_regex(pattern: str):
    """glob → regex: `**` пересекает «/», `*` и `?` — нет; путь без glob = префикс-папка."""
    p = pattern[2:] if pattern.startswith("./") else pattern
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += ".*"
            i += 2
        elif p[i] == "*":
            out += "[^/]*"
            i += 1
        elif p[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    if not re.search(r"[*?]", pattern):          # "src/auth" == вся папка или файл
        out = out.rstrip("/") + "(?:/.*)?"
    return re.compile(f"^{out}$")


def outside_owns(changed, owns):
    if owns == ["**"]:
        return []
    rx = [glob_to_regex(p) for p in owns]
    return [f for f in changed if not any(r.match(f) for r in rx)]


# ───────────────────────── выполнение подзадачи ─────────────────────────
def build_prompt(sub, task):
    test = f"\n- для проверки используй: {task['test_cmd']}" if task.get("test_cmd") else ""
    retry = (f"\n\nВНИМАНИЕ: предыдущая попытка завершилась ошибкой:\n{sub['last_error']}\n"
             f"Учти это.") if sub.get("last_error") else ""
    return f"""Ты — один из агентов, параллельно работающих над общей задачей.

ОБЩАЯ ЗАДАЧА: {task['prompt']}

ТВОЯ ПОДЗАДАЧА: {sub['title']}
{sub['prompt']}

ПРАВИЛА:
- изменяй только файлы в: {', '.join(sub['owns'])}
- не выполняй git commit / push / checkout / reset — это сделает оркестратор
- по завершении запусти релевантные тесты{test}
- в конце кратко опиши, что сделано{retry}"""


def execute(job):
    sub, task = job["subtask"], job["task"]
    repo = WORK / "repos" / task["id"]
    wt = WORK / "wt" / sub["id"].replace(":", "_")

    # 1. подготовка worktree
    with git_lock:
        if not repo.exists():
            sh(["git", "clone", task["repo"], str(repo)])
        sh(["git", "fetch", "origin", "--prune"], cwd=repo)
        sh(["git", "worktree", "prune"], cwd=repo, check=False)
        if wt.exists():
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)
            shutil.rmtree(wt, ignore_errors=True)
        sh(["git", "worktree", "add", "-B", sub["branch"], str(wt),
            f"origin/{sub['base_ref']}"], cwd=repo)

    try:
        # 1b. разрешитель конфликта: начинаем слияние сами, агент правит только маркеры
        if sub.get("resolves"):
            sh(["git", "-c", "user.name=ccd", "-c", "user.email=ccd@local",
                "merge", "--no-commit", "--no-ff", f"origin/{task['integration']}"],
               cwd=wt, check=False)

        # 2. запуск Claude Code (headless)
        cmd = ["claude", "-p", build_prompt(sub, task),
               "--output-format", "json",
               "--max-turns", str(CFG.get("max_turns", 40)),
               "--permission-mode", CFG.get("permission_mode", "acceptEdits"),
               "--allowedTools", CFG.get("allowed_tools", DEFAULT_TOOLS)]
        if CFG.get("model"):
            cmd += ["--model", CFG["model"]]
        r = subprocess.run(cmd, cwd=wt, capture_output=True, text=True,
                           timeout=CFG.get("timeout_s", 3600))
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise JobError(f"claude вернул не-JSON: {r.stdout[-500:] or r.stderr[-500:]}")
        if data.get("is_error"):
            raise JobError(f"claude error: {str(data.get('result'))[:500]}")
        cost = float(data.get("total_cost_usd") or 0)
        summary = str(data.get("result") or "")[:2000]

        # 3. проверка владения файлами
        sh(["git", "add", "-A"], cwd=wt)
        changed = sh(["git", "diff", "--cached", "--name-only"], cwd=wt).stdout.splitlines()
        bad = outside_owns(changed, sub["owns"])
        if bad:
            raise JobError(f"изменены файлы вне owns {sub['owns']}: {bad[:10]}", retryable=True)
        if sub.get("resolves"):
            left = sh(["git", "grep", "--cached", "-n", "-E", r"^(<{7} |>{7} )"],
                      cwd=wt, check=False)
            if left.returncode == 0:
                raise JobError(f"остались маркеры конфликта:\n{left.stdout[:800]}", retryable=True)

        # 4. тесты на этом устройстве (здесь и используются ресурсы воркера)
        if task.get("test_cmd"):
            t = subprocess.run(["bash", "-lc", task["test_cmd"]], cwd=wt,
                               capture_output=True, text=True,
                               timeout=CFG.get("test_timeout_s", 1800))
            if t.returncode:
                tail = (t.stdout + t.stderr)[-1500:]
                raise JobError(f"тесты не прошли:\n{tail}", retryable=True)
            # файлы, созданные тестами, в индекс не попадают: он собран до их запуска

        # 5. коммит и push ветки подзадачи (при начатом слиянии commit создаёт merge-коммит)
        merging = sh(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                     cwd=wt, check=False).returncode == 0
        if changed or merging:
            sh(["git", "-c", "user.name=ccd", "-c", "user.email=ccd@local",
                "commit", "--allow-empty", "-m", f"{sub['key']}: {sub['title']}"], cwd=wt)
        sh(["git", "push", "-f", "origin", f"HEAD:refs/heads/{sub['branch']}"], cwd=wt)

        api.post(f"/subtasks/{sub['id']}/complete",
                 json={"summary": summary, "cost": cost}).raise_for_status()
    finally:
        with git_lock:
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)


def run_job(job, sem):
    sid = job["subtask"]["id"]
    try:
        execute(job)
    except JobError as e:
        post_fail(sid, str(e), e.retryable)
    except subprocess.TimeoutExpired:
        post_fail(sid, "timeout", True)
    except Exception as e:  # noqa: BLE001
        post_fail(sid, f"{type(e).__name__}: {e}"[:1500], True)
    finally:
        sem.release()


def post_fail(sid, error, retryable):
    try:
        api.post(f"/subtasks/{sid}/fail", json={"error": error, "retryable": retryable})
    except Exception as e:  # noqa: BLE001
        print(f"не удалось сообщить об ошибке {sid}: {e}", file=sys.stderr)


# ───────────────────────── цикл воркера ─────────────────────────
def heartbeat_loop():
    while True:
        try:
            api.post("/workers/heartbeat", json={"id": WID, "load": psutil.cpu_percent()})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(20)


def main():
    global WID, CFG, WORK, api
    if len(sys.argv) < 2:
        raise SystemExit("usage: worker.py worker.json")
    CFG = json.load(open(sys.argv[1]))
    WORK = Path(CFG["workdir"]).expanduser()
    (WORK / "repos").mkdir(parents=True, exist_ok=True)
    (WORK / "wt").mkdir(parents=True, exist_ok=True)
    api = httpx.Client(base_url=CFG["server"],
                       headers={"Authorization": f"Bearer {CFG['token']}"}, timeout=60)
    poll = CFG.get("poll_s", 5)

    WID = api.post("/workers/register", json={
        "name": CFG.get("name", socket.gethostname()),
        "slots": CFG["slots"], "labels": CFG.get("labels", [])}).json()["id"]
    print(f"worker {WID} зарегистрирован, слотов: {CFG['slots']}", flush=True)
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    pool = ThreadPoolExecutor(CFG["slots"])
    sem = threading.BoundedSemaphore(CFG["slots"])
    while True:
        # backpressure: нет слота или устройство перегружено → ждём
        if psutil.cpu_percent(interval=1) > CFG.get("cpu_limit", 85) \
                or not sem.acquire(blocking=False):
            time.sleep(poll)
            continue
        try:
            r = api.post("/claim", json={"worker_id": WID})
        except Exception:  # noqa: BLE001
            sem.release()
            time.sleep(10)
            continue
        if r.status_code != 200:
            sem.release()
            time.sleep(poll)
            continue
        job = r.json()
        print(f"взята подзадача {job['subtask']['id']}", flush=True)
        pool.submit(run_job, job, sem)


if __name__ == "__main__":
    main()
