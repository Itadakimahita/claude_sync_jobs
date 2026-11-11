#!/usr/bin/env python3
"""ccd submit | status | watch | workers | tasks"""
import argparse
import os
import sys
import time

import httpx

SERVER = os.environ.get("CCD_SERVER", "http://127.0.0.1:8787")

ICON = {"pending": "⏳", "running": "🔄", "completed": "📦", "merged": "✅",
        "conflict": "⚠️ ", "failed": "❌"}


def client():
    token = os.environ.get("CCD_TOKEN")
    if not token:
        sys.exit("Задайте переменную окружения CCD_TOKEN")
    return httpx.Client(base_url=SERVER, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def call(api, method, path, **kw):
    try:
        r = api.request(method, path, **kw)
    except httpx.HTTPError as e:
        sys.exit(f"координатор недоступен ({SERVER}): {e}")
    if r.status_code >= 400:
        sys.exit(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def show(api, tid):
    d = call(api, "GET", f"/tasks/{tid}")
    t = d["task"]
    print(f"\nЗадача {t['id']} [{t['status']}]  стоимость ≈ ${d['total_cost']:.2f}")
    if t["error"]:
        print("  ошибка:", t["error"][:300])
    for s in d["subtasks"]:
        print(f"  {ICON.get(s['status'], '?')} {s['key']:<10} {s['status']:<10} "
              f"{(s['worker'] or '-'):<9} {s['title']}")
    if t["status"] in ("done", "failed"):
        print(f"\nИнтеграционная ветка: {t['integration']}")
    return t["status"]


def main():
    p = argparse.ArgumentParser(prog="ccd")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("submit", help="отправить задачу")
    s.add_argument("prompt")
    s.add_argument("--repo", required=True)
    s.add_argument("--base", default="main")
    s.add_argument("--test", default="")

    for name in ("status", "watch"):
        x = sp.add_parser(name)
        x.add_argument("id")
    sp.add_parser("workers")
    sp.add_parser("tasks")

    a = p.parse_args()
    api = client()
    if a.cmd == "submit":
        tid = call(api, "POST", "/tasks", json={"prompt": a.prompt, "repo": a.repo,
                                                "base": a.base, "test_cmd": a.test})["id"]
        print("создана задача", tid)
    elif a.cmd == "status":
        show(api, a.id)
    elif a.cmd == "watch":
        try:
            while show(api, a.id) not in ("done", "failed"):
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    elif a.cmd == "tasks":
        for t in call(api, "GET", "/tasks"):
            print(f"{t['id']}  {t['status']:<9} {t['prompt'][:70]}")
    elif a.cmd == "workers":
        for w in call(api, "GET", "/workers"):
            age = time.time() - w["last_seen"]
            state = "online" if age < 60 else f"offline {int(age)}с"
            print(f"{w['id']}  {w['name']:<12} слотов={w['slots']}  {state}")


if __name__ == "__main__":
    main()
