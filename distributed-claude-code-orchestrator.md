# CCD — распределённый оркестратор агентов Claude Code

> Одна задача → автоматическая декомпозиция → параллельная работа агентов Claude Code на нескольких устройствах → синхронизация кода через git → слияние и проверка.

Документ описывает идею, архитектуру, протокол и **рабочий MVP-код** (координатор, воркер, CLI), а также развёртывание, безопасность, лимиты и план развития.

---

## Содержание

1. [Идея и цели](#1-%D0%B8%D0%B4%D0%B5%D1%8F-%D0%B8-%D1%86%D0%B5%D0%BB%D0%B8)
2. [Важные факты и ограничения](#2-%D0%B2%D0%B0%D0%B6%D0%BD%D1%8B%D0%B5-%D1%84%D0%B0%D0%BA%D1%82%D1%8B-%D0%B8-%D0%BE%D0%B3%D1%80%D0%B0%D0%BD%D0%B8%D1%87%D0%B5%D0%BD%D0%B8%D1%8F)
3. [Принципы проектирования](#3-%D0%BF%D1%80%D0%B8%D0%BD%D1%86%D0%B8%D0%BF%D1%8B-%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D1%8F)
4. [Архитектура](#4-%D0%B0%D1%80%D1%85%D0%B8%D1%82%D0%B5%D0%BA%D1%82%D1%83%D1%80%D0%B0)
5. [Жизненный цикл задачи](#5-%D0%B6%D0%B8%D0%B7%D0%BD%D0%B5%D0%BD%D0%BD%D1%8B%D0%B9-%D1%86%D0%B8%D0%BA%D0%BB-%D0%B7%D0%B0%D0%B4%D0%B0%D1%87%D0%B8)
6. [Декомпозиция задачи](#6-%D0%B4%D0%B5%D0%BA%D0%BE%D0%BC%D0%BF%D0%BE%D0%B7%D0%B8%D1%86%D0%B8%D1%8F-%D0%B7%D0%B0%D0%B4%D0%B0%D1%87%D0%B8)
7. [Синхронизация кода (git-стратегия)](#7-%D1%81%D0%B8%D0%BD%D1%85%D1%80%D0%BE%D0%BD%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F-%D0%BA%D0%BE%D0%B4%D0%B0-git-%D1%81%D1%82%D1%80%D0%B0%D1%82%D0%B5%D0%B3%D0%B8%D1%8F)
8. [Модель данных](#8-%D0%BC%D0%BE%D0%B4%D0%B5%D0%BB%D1%8C-%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85)
9. [HTTP API координатора](#9-http-api-%D0%BA%D0%BE%D0%BE%D1%80%D0%B4%D0%B8%D0%BD%D0%B0%D1%82%D0%BE%D1%80%D0%B0)
10. [Реализация MVP](#10-%D1%80%D0%B5%D0%B0%D0%BB%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F-mvp)
11. [Развёртывание](#11-%D1%80%D0%B0%D0%B7%D0%B2%D1%91%D1%80%D1%82%D1%8B%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5)
12. [Безопасность](#12-%D0%B1%D0%B5%D0%B7%D0%BE%D0%BF%D0%B0%D1%81%D0%BD%D0%BE%D1%81%D1%82%D1%8C)
13. [Лимиты, стоимость, ресурсы](#13-%D0%BB%D0%B8%D0%BC%D0%B8%D1%82%D1%8B-%D1%81%D1%82%D0%BE%D0%B8%D0%BC%D0%BE%D1%81%D1%82%D1%8C-%D1%80%D0%B5%D1%81%D1%83%D1%80%D1%81%D1%8B)
14. [Отказоустойчивость](#14-%D0%BE%D1%82%D0%BA%D0%B0%D0%B7%D0%BE%D1%83%D1%81%D1%82%D0%BE%D0%B9%D1%87%D0%B8%D0%B2%D0%BE%D1%81%D1%82%D1%8C)
15. [Пример сквозного сценария](#15-%D0%BF%D1%80%D0%B8%D0%BC%D0%B5%D1%80-%D1%81%D0%BA%D0%B2%D0%BE%D0%B7%D0%BD%D0%BE%D0%B3%D0%BE-%D1%81%D1%86%D0%B5%D0%BD%D0%B0%D1%80%D0%B8%D1%8F)
16. [Roadmap](#16-roadmap)
17. [Что проверить перед использованием](#17-%D1%87%D1%82%D0%BE-%D0%BF%D1%80%D0%BE%D0%B2%D0%B5%D1%80%D0%B8%D1%82%D1%8C-%D0%BF%D0%B5%D1%80%D0%B5%D0%B4-%D0%B8%D1%81%D0%BF%D0%BE%D0%BB%D1%8C%D0%B7%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5%D0%BC)

---

## 1. Идея и цели

**Проблема.** У вас несколько устройств (ноутбук, десктоп, домашний сервер, VPS), на всех установлен Claude Code под одним аккаунтом. Сейчас каждый экземпляр работает сам по себе: одну большую задачу приходится вручную делить, запускать сессии на разных машинах и вручную сливать результаты.

**Решение.** Программа CCD:

* принимает **одну задачу** на естественном языке;
* автоматически **разбивает** её на независимые подзадачи;
* **раздаёт** подзадачи агентам Claude Code на разных устройствах с учётом их загрузки;
* **синхронизирует код** через git (ветка на подзадачу + интеграционная ветка);
* **сливает** результаты, разрешает конфликты отдельным агентом и запускает финальную проверку;
* показывает единый статус.

**Цели**


| Цель                                                                | Как достигается                                                                                                                            |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Параллелизм                                                  | Подзадачи с непересекающимися файлами выполняются одновременно на разных машинах |
| Использование ресурсов всех устройств | Тяжёлые части (сборка, тесты, запуск кода) выполняются локально на воркерах                |
| Единый код                                                     | Git — единственный источник истины, интеграционная ветка                                                   |
| Простота                                                        | Один координатор + лёгкие воркеры, без сложной инфраструктуры                                        |
| Контроль затрат                                           | Лимиты ходов, бюджета, числа слотов                                                                                         |

**Не цели (для MVP):** собственная реализация LLM-цикла, GUI, мультитенантность, кластерный планировщик уровня Kubernetes.

---

## 2. Важные факты и ограничения

Чтобы не строить на ложных ожиданиях:

1. **«Мозги» агента работают не на ваших устройствах.** Рассуждения модели выполняются на серверах Anthropic. Локальные устройства дают агенту *руки*: чтение/запись файлов, запуск тестов, сборок, линтеров, скриптов, браузеров и т. д. Поэтому выигрыш по ресурсам реален для **тяжёлых инструментов**, а не для самой генерации.
2. **Лимиты общие на аккаунт.** Больше устройств ≠ больше токенов. N параллельных агентов тратят квоту примерно в N раз быстрее. Распределение ускоряет *время выполнения*, а не повышает потолок использования.
3. **Параллелизм работает только на независимых подзадачах.** Если всё завязано на общее состояние (общие типы, миграции, конфиги), качество декомпозиции становится критичным.
4. **Авторизация.** Для автоматизации на нескольких машинах надёжнее API-ключ (`ANTHROPIC_API_KEY`). Если используете подписочную авторизацию на нескольких устройствах, проверьте актуальные условия использования Anthropic — автоматизированные схемы могут быть ограничены.
5. **Что уже есть в Claude Code** (проверьте актуальную документацию, функции развиваются): git worktrees (`--worktree`), subagents, экспериментальные Agent Teams, headless-режим (`claude -p`), Agent SDK, обмен сообщениями между сессиями (в том числе на разных машинах). CCD строится *поверх* этого и добавляет: кросс-машинную очередь, планировщик с учётом ресурсов, git-интеграцию и слияние.

---

## 3. Принципы проектирования

* **Pull-модель воркеров.** Воркер сам опрашивает координатор (`/claim`). Не нужно открывать входящие порты на ноутбуках за NAT.
* **Git как шина данных для кода.** Не Syncthing/Dropbox: git даёт атомарные коммиты, merge, историю, откат.
* **Изоляция через worktree.** Каждая подзадача — отдельный `git worktree` и ветка. Агенты не затирают файлы друг друга.
* **Владение файлами (file ownership).** Планировщик назначает каждой подзадаче набор путей (`owns`). Воркер проверяет, что агент не вышел за них.
* **Идемпотентность и повторы.** Любая подзадача может быть безопасно перезапущена на другом воркере.
* **Координатор тонкий.** Он хранит состояние, планирует и сливает; всю «тяжёлую» работу делают воркеры.

---

## 4. Архитектура

```
                        ┌───────────────────────────────┐
   ccd submit "…"  ───► │          КООРДИНАТОР          │
   ccd status / watch   │  FastAPI + SQLite             │
                        │  ├─ Planner  (claude -p, RO)  │
                        │  ├─ Scheduler (очередь, DAG)  │
                        │  ├─ Integrator (git merge)    │
                        │  └─ Reaper  (потерянные jobs) │
                        └──────────────┬────────────────┘
                                       │ HTTPS/HTTP по Tailscale/WireGuard
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
     ┌────────▼───────┐       ┌────────▼───────┐       ┌────────▼───────┐
     │  ВОРКЕР A      │       │  ВОРКЕР B      │       │  ВОРКЕР C      │
     │  ноутбук       │       │  десктоп       │       │  VPS/сервер    │
     │  слотов: 2     │       │  слотов: 4     │       │  слотов: 8     │
     │  worktree+     │       │  worktree+     │       │  worktree+     │
     │  claude -p     │       │  claude -p     │       │  claude -p     │
     └────────┬───────┘       └────────┬───────┘       └────────┬───────┘
              │   git push ccd/<task>/<key>                     │
              └────────────────────────┬────────────────────────┘
                                       ▼
                        ┌───────────────────────────────┐
                        │   GIT REMOTE (origin)         │
                        │   main                        │
                        │   ccd/<task>/integration      │
                        │   ccd/<task>/A, /B, /C, …     │
                        └───────────────────────────────┘
```

### Компоненты

**Координатор**

* принимает задачи, хранит состояние в SQLite;
* **Planner** — запускает Claude Code в режиме «только чтение» и получает JSON с подзадачами;
* **Scheduler** — выдаёт воркерам готовые подзадачи (те, у кого все зависимости слиты);
* **Integrator** — сливает ветки подзадач в интеграционную; при конфликте создаёт подзадачу-«разрешитель»;
* **Reaper** — возвращает в очередь задания, воркер которых пропал.

**Воркер**

* регистрируется, шлёт heartbeat с нагрузкой CPU;
* берёт задания, пока есть свободные слоты и CPU ниже порога;
* создаёт worktree, запускает `claude -p`, проверяет владение файлами, запускает тесты, коммитит, пушит ветку, рапортует.

**Git remote**

* любой: GitHub/GitLab/Gitea или простой bare-репозиторий на координаторе (`git init --bare`).

---

## 5. Жизненный цикл задачи

```
submit ─► PLANNING ─► RUNNING ─► (все подзадачи слиты) ─► VERIFY ─► DONE
              │           │                                  │
              └─► FAILED  └─► подзадача FAILED ─► task FAILED └─► FAILED
```

1. **Submit.** Пользователь отправляет `prompt`, `repo`, `base` (ветка), опционально `test_cmd`.
2. **Planning.** Координатор клонирует репозиторий, создаёт `ccd/<task>/integration` от `base`, запускает планировщика. Результат валидируется: уникальные ключи, существующие зависимости, отсутствие циклов, непересечение `owns` у независимых подзадач.
3. **Scheduling.** Подзадача готова, когда все `deps` в статусе `merged`. Воркер забирает её через `/claim`.
4. **Execution (на воркере).** worktree от `origin/<base_ref>` (по умолчанию — свежая интеграционная ветка) → `claude -p` → проверка владения → тесты → коммит → push ветки `ccd/<task>/<key>` → `complete`.
5. **Integration.** Координатор сливает ветку в интеграционную (`--no-ff`) и пушит. Конфликт → создаётся подзадача `<key>-fixN`, которая в своей ветке мерджит интеграционную и разрешает конфликты.
6. **Verify.** Когда все рабочие подзадачи слиты, создаётся финальная подзадача `VERIFY`: запуск тестов и минимальные исправления.
7. **Done.**`VERIFY` слита → задача `done`. Интеграционная ветка готова к PR/merge в `base`.

---

## 6. Декомпозиция задачи

Качество разбиения — главный фактор успеха. Планировщик получает репозиторий **только на чтение** (`Read,Grep,Glob`) и обязан вернуть строгий JSON.

### Формат плана

```json
{
  "subtasks": [
    {
      "key": "A",
      "title": "Модуль авторизации (backend)",
      "prompt": "Реализуй JWT-авторизацию… Критерии готовности: …",
      "owns": ["src/auth/**", "tests/auth/**"],
      "deps": []
    },
    {
      "key": "B",
      "title": "UI формы логина",
      "prompt": "…",
      "owns": ["web/src/login/**"],
      "deps": ["A"]
    }
  ]
}
```

### Правила для планировщика (вшиты в промпт)

* у каждой подзадачи **непересекающиеся**`owns`;
* общие файлы (lock-файлы, корневые конфиги, общие типы) принадлежат **ровно одной** подзадаче;
* зависимость между подзадачами выражается через `deps`;
* 2–8 подзадач; если распараллелить нельзя — одна подзадача;
* `prompt` самодостаточен: цель, контекст, критерии готовности.

### Валидация на стороне координатора

* ключи уникальны;
* все `deps` ссылаются на существующие ключи;
* граф зависимостей ациклический;
* для пар подзадач, **не связанных** отношением «предок–потомок», шаблоны `owns` не пересекаются (эвристика по статическому префиксу шаблона).

Если валидация не прошла — задача получает статус `failed` с понятной ошибкой (в v2 — автоматический повторный запрос к планировщику с описанием ошибки).

---

## 7. Синхронизация кода (git-стратегия)

```
main ──────────────────────────────────────────────────────►
  │
  └─► ccd/T1/integration ──●──────●──────●──────●───► (PR → main)
          ▲                │      │      │      │
          │   merge A      │  merge C    │  merge VERIFY
          │            merge B           merge B-fix1
  ccd/T1/A ─┘   ccd/T1/B ───┘  ccd/T1/C ──┘
```

* **Ветка подзадачи:**`ccd/<task>/<key>`. Создаётся воркером от `origin/<base_ref>`.
* **`base_ref`:** по умолчанию — `ccd/<task>/integration` на момент старта подзадачи. Поэтому зависимые подзадачи видят результаты своих зависимостей.
* **Слияние:** только координатор, последовательно (мьютекс), `git merge --no-ff`.
* **Конфликт:** подзадача-разрешитель стартует от конфликтной ветки, выполняет `git merge origin/<integration>`, разрешает конфликты с сохранением смысла обеих сторон и прогоняет тесты. Её слияние — fast-forward-подобное.
* **Агенты не делают `commit/push/checkout`.** Коммитит и пушит воркер — так контролируется, что именно попадает в историю (и проверка `owns` не обходится).
* **Рабочие копии на воркерах** — один клон на задачу + worktree на подзадачу; удаляются после завершения.

---

## 8. Модель данных

SQLite, три таблицы.

```sql
CREATE TABLE tasks(
  id TEXT PRIMARY KEY,
  prompt TEXT, repo TEXT, base TEXT, test_cmd TEXT,
  integration TEXT,            -- имя интеграционной ветки
  status TEXT,                 -- planning | running | done | failed
  error TEXT, created REAL
);

CREATE TABLE subtasks(
  id TEXT PRIMARY KEY,         -- "<task>:<key>"
  task_id TEXT, key TEXT, title TEXT, prompt TEXT,
  owns TEXT,                   -- JSON-массив glob-шаблонов
  deps TEXT,                   -- JSON-массив ключей
  base_ref TEXT, branch TEXT,
  status TEXT,                 -- pending | running | completed | merged | conflict | failed
  worker TEXT, attempts INTEGER DEFAULT 0,
  cost REAL DEFAULT 0, summary TEXT,
  resolves TEXT,               -- ключ подзадачи, чей конфликт решает эта
  started REAL, finished REAL
);

CREATE TABLE workers(
  id TEXT PRIMARY KEY, name TEXT, slots INTEGER,
  labels TEXT, last_seen REAL
);
```

---

## 9. HTTP API координатора

Все запросы: заголовок `Authorization: Bearer <CCD_TOKEN>`.


| Метод | Путь                   | Назначение                                                |
| ---------- | -------------------------- | ------------------------------------------------------------------- |
| POST       | `/tasks`                   | Создать задачу`{prompt, repo, base, test_cmd}`→`{id}` |
| GET        | `/tasks/{id}`              | Состояние задачи и подзадач                 |
| GET        | `/tasks`                   | Список задач                                             |
| POST       | `/workers/register`        | Регистрация воркера →`{id}`                      |
| POST       | `/workers/heartbeat`       | `{id, load}`                                                        |
| GET        | `/workers`                 | Список воркеров                                       |
| POST       | `/claim`                   | `{worker_id}`→ задание или`204`                          |
| POST       | `/subtasks/{sid}/complete` | `{summary, cost}`— ветка уже запушена              |
| POST       | `/subtasks/{sid}/fail`     | `{error, retryable}`                                                |

---

## 10. Реализация MVP

### 10.1. Структура проекта

```
ccd/
├── requirements.txt
├── server.py          # координатор
├── worker.py          # воркер
├── cli.py             # командная строка
├── worker.example.json
└── README.md
```

`requirements.txt`:

```
fastapi
uvicorn
httpx
psutil
```

Предполагается, что на всех машинах установлены `git` и `claude` (Claude Code) и выполнен вход/задан ключ.

### 10.2. `server.py` — координатор

```python
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
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

TOKEN = os.environ["CCD_TOKEN"]
DATA = Path(os.environ.get("CCD_DATA", "./data"))
(DATA / "repos").mkdir(parents=True, exist_ok=True)

WORKER_TIMEOUT = 90   # сек без heartbeat → воркер считается потерянным
MAX_ATTEMPTS = 3

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
def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
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


# ───────────────────────── планировщик ─────────────────────────
PLAN_PROMPT = """Ты — архитектор-планировщик. Изучи репозиторий (только чтение) и разбей
задачу на независимые подзадачи для параллельной работы разных агентов.

Правила:
- у каждой подзадачи свой непересекающийся набор файлов/папок (owns, glob-шаблоны);
- общие файлы (конфиги, lock-файлы, общие типы) отдай ровно одной подзадаче;
- если подзадача зависит от результата другой — укажи deps (список ключей);
- 2–8 подзадач; если задачу нельзя разумно распараллелить — верни одну;
- prompt подзадачи самодостаточен: цель, контекст, критерии готовности.

Ответь ТОЛЬКО JSON без пояснений и без markdown:
{"subtasks":[{"key":"A","title":"...","prompt":"...","owns":["src/x/**"],"deps":[]}]}

ЗАДАЧА:
"""


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
    by = {s["key"]: s for s in subs}
    assert len(by) == len(subs), "дублирующиеся ключи подзадач"
    assert 1 <= len(subs) <= 12, "некорректное число подзадач"
    for s in subs:
        assert s.get("owns"), f"{s['key']}: пустой owns"
        assert set(s.get("deps", [])) <= set(by), f"{s['key']}: неизвестная зависимость"

    # ациклический граф + предки
    anc = {}

    def visit(k, stack=()):
        assert k not in stack, "цикл в зависимостях"
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
            assert not patterns_overlap(by[a]["owns"], by[b]["owns"]), \
                f"пересечение owns между {a} и {b}"


def add_subtask(task, key, title, prompt, owns, deps, base_ref=None, resolves=None):
    run("""INSERT INTO subtasks(id,task_id,key,title,prompt,owns,deps,base_ref,branch,status,resolves)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        f"{task['id']}:{key}", task["id"], key, title, prompt,
        json.dumps(owns), json.dumps(deps),
        base_ref or task["integration"], f"ccd/{task['id']}/{key}",
        "pending", resolves)


def plan_task(tid):
    try:
        task = get_task(tid)
        repo = DATA / "repos" / tid
        sh(["git", "clone", task["repo"], str(repo)])
        sh(["git", "checkout", "-B", task["integration"], f"origin/{task['base']}"], cwd=repo)
        sh(["git", "push", "-u", "origin", task["integration"]], cwd=repo)

        out = sh(["claude", "-p", PLAN_PROMPT + task["prompt"],
                  "--output-format", "json", "--max-turns", "25",
                  "--allowedTools", "Read,Grep,Glob"], cwd=repo).stdout
        text = json.loads(out)["result"]
        subs = json.loads(text[text.index("{"): text.rindex("}") + 1])["subtasks"]
        validate(subs)
        for s in subs:
            add_subtask(task, s["key"], s["title"], s["prompt"], s["owns"], s.get("deps", []))
        run("UPDATE tasks SET status='running' WHERE id=?", tid)
    except Exception as e:  # noqa: BLE001
        run("UPDATE tasks SET status='failed', error=? WHERE id=?", str(e), tid)


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
                    f"Ветка уже содержит работу подзадачи «{sub['title']}». "
                    f"Выполни `git merge origin/{task['integration']}`, разреши все конфликты, "
                    f"сохранив смысл обеих сторон, затем запусти тесты и убедись, что всё проходит. "
                    f"Не делай commit — это сделает оркестратор (оставь файлы в рабочем дереве, "
                    f"завершив слияние через `git add -A`).",
                    ["**"], [], base_ref=sub["branch"], resolves=sub["key"])
                return
            sh(["git", "push", "origin", task["integration"]], cwd=repo)

        run("UPDATE subtasks SET status='merged' WHERE id=?", sid)
        if sub["resolves"]:
            run("UPDATE subtasks SET status='merged' WHERE task_id=? AND key=?",
                task["id"], sub["resolves"])
        advance(task["id"])
    except Exception as e:  # noqa: BLE001
        run("UPDATE tasks SET status='failed', error=? WHERE id=?", f"integrate {sid}: {e}", task["id"])


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
def reaper():
    while True:
        time.sleep(30)
        cutoff = time.time() - WORKER_TIMEOUT
        with lock:
            db.execute("""UPDATE subtasks SET status='failed', summary='worker lost, attempts exhausted'
                          WHERE status='running' AND attempts>=?
                          AND worker IN (SELECT id FROM workers WHERE last_seen<?)""",
                       (MAX_ATTEMPTS, cutoff))
            db.execute("""UPDATE subtasks SET status='pending', worker=NULL, summary='worker lost'
                          WHERE status='running'
                          AND worker IN (SELECT id FROM workers WHERE last_seen<?)""", (cutoff,))


threading.Thread(target=reaper, daemon=True).start()


# ───────────────────────── API ─────────────────────────
app = FastAPI(title="ccd coordinator")


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
        raise HTTPException(404)
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
    run("UPDATE subtasks SET status='completed', summary=?, cost=cost+?, finished=? WHERE id=?",
        body.summary, body.cost, time.time(), sid)
    threading.Thread(target=integrate, args=(sid,), daemon=True).start()
    return {"ok": True}


@app.post("/subtasks/{sid}/fail", dependencies=[Depends(auth)])
def fail(sid: str, body: FailReq):
    s = rows("SELECT * FROM subtasks WHERE id=?", sid)[0]
    if body.retryable and s["attempts"] < MAX_ATTEMPTS:
        run("UPDATE subtasks SET status='pending', worker=NULL, summary=? WHERE id=?", body.error, sid)
    else:
        run("UPDATE subtasks SET status='failed', summary=? WHERE id=?", body.error, sid)
        run("UPDATE tasks SET status='failed', error=? WHERE id=?",
            f"{s['key']}: {body.error[:500]}", s["task_id"])
    return {"ok": True}
```

Запуск:

```bash
export CCD_TOKEN="длинный-случайный-секрет"
uvicorn server:app --host 0.0.0.0 --port 8787
```

### 10.3. `worker.py` — воркер

```python
#!/usr/bin/env python3
"""CCD worker: берёт подзадачи, запускает Claude Code в git worktree."""
import fnmatch
import json
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

CFG = json.load(open(sys.argv[1]))
WORK = Path(CFG["workdir"]).expanduser()
(WORK / "repos").mkdir(parents=True, exist_ok=True)
(WORK / "wt").mkdir(parents=True, exist_ok=True)

api = httpx.Client(base_url=CFG["server"],
                   headers={"Authorization": f"Bearer {CFG['token']}"}, timeout=60)
git_lock = threading.Lock()
WID = None


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{r.stderr.strip() or r.stdout.strip()}")
    return r


class JobError(Exception):
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


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
        if wt.exists():
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)
            shutil.rmtree(wt, ignore_errors=True)
        sh(["git", "worktree", "add", "-B", sub["branch"], str(wt),
            f"origin/{sub['base_ref']}"], cwd=repo)

    try:
        # 2. запуск Claude Code (headless)
        cmd = ["claude", "-p", build_prompt(sub, task),
               "--output-format", "json",
               "--max-turns", str(CFG.get("max_turns", 40)),
               "--permission-mode", CFG.get("permission_mode", "acceptEdits"),
               "--allowedTools", CFG["allowed_tools"]]
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
        changed = sh(["git", "diff", "--cached", "--name-only"], cwd=wt).stdout.split()
        if sub["owns"] != ["**"]:
            pats = [p.replace("**", "*") for p in sub["owns"]]  # fnmatch: * захватывает "/"
            bad = [f for f in changed if not any(fnmatch.fnmatch(f, p) for p in pats)]
            if bad:
                raise JobError(f"изменены файлы вне owns {sub['owns']}: {bad[:10]}", retryable=True)

        # 4. тесты на этом устройстве (здесь и используются ресурсы воркера)
        if task.get("test_cmd"):
            t = subprocess.run(["bash", "-lc", task["test_cmd"]], cwd=wt,
                               capture_output=True, text=True,
                               timeout=CFG.get("test_timeout_s", 1800))
            if t.returncode:
                tail = (t.stdout + t.stderr)[-1500:]
                raise JobError(f"тесты не прошли:\n{tail}", retryable=True)

        # 5. коммит и push ветки подзадачи
        if changed:
            sh(["git", "-c", "user.name=ccd", "-c", "user.email=ccd@local",
                "commit", "-m", f"{sub['key']}: {sub['title']}"], cwd=wt)
        sh(["git", "push", "-f", "origin", f"HEAD:refs/heads/{sub['branch']}"], cwd=wt)

        api.post(f"/subtasks/{sub['id']}/complete", json={"summary": summary, "cost": cost})
    finally:
        with git_lock:
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)


def run_job(job, sem):
    sid = job["subtask"]["id"]
    try:
        execute(job)
    except JobError as e:
        api.post(f"/subtasks/{sid}/fail", json={"error": str(e), "retryable": e.retryable})
    except subprocess.TimeoutExpired:
        api.post(f"/subtasks/{sid}/fail", json={"error": "timeout", "retryable": True})
    except Exception as e:  # noqa: BLE001
        api.post(f"/subtasks/{sid}/fail", json={"error": f"{type(e).__name__}: {e}"[:1500],
                                                "retryable": True})
    finally:
        sem.release()


def heartbeat_loop():
    while True:
        try:
            api.post("/workers/heartbeat", json={"id": WID, "load": psutil.cpu_percent()})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(20)


def main():
    global WID
    WID = api.post("/workers/register", json={
        "name": CFG.get("name", socket.gethostname()),
        "slots": CFG["slots"], "labels": CFG.get("labels", [])}).json()["id"]
    print(f"worker {WID} зарегистрирован, слотов: {CFG['slots']}")
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    pool = ThreadPoolExecutor(CFG["slots"])
    sem = threading.BoundedSemaphore(CFG["slots"])
    while True:
        # backpressure: нет слота или устройство перегружено → ждём
        if psutil.cpu_percent(interval=1) > CFG.get("cpu_limit", 85) \
                or not sem.acquire(blocking=False):
            time.sleep(5)
            continue
        try:
            r = api.post("/claim", json={"worker_id": WID})
        except Exception:  # noqa: BLE001
            sem.release()
            time.sleep(10)
            continue
        if r.status_code == 204:
            sem.release()
            time.sleep(5)
            continue
        pool.submit(run_job, r.json(), sem)


if __name__ == "__main__":
    main()
```

Пример `worker.example.json`:

```json
{
  "server": "http://100.64.0.1:8787",
  "token": "тот-же-секрет-что-у-координатора",
  "name": "laptop",
  "workdir": "~/.ccd",
  "slots": 2,
  "cpu_limit": 85,
  "max_turns": 40,
  "timeout_s": 3600,
  "test_timeout_s": 1800,
  "permission_mode": "acceptEdits",
  "allowed_tools": "Read,Edit,Write,Grep,Glob,Bash(npm test:*),Bash(npm run:*),Bash(pytest:*),Bash(git diff:*),Bash(git status:*)",
  "labels": ["node", "python"]
}
```

### 10.4. `cli.py` — командная строка

```python
#!/usr/bin/env python3
"""ccd submit | status | watch | workers"""
import argparse
import os
import sys
import time

import httpx

SERVER = os.environ.get("CCD_SERVER", "http://127.0.0.1:8787")
api = httpx.Client(base_url=SERVER,
                   headers={"Authorization": f"Bearer {os.environ['CCD_TOKEN']}"}, timeout=30)

ICON = {"pending": "⏳", "running": "🔄", "completed": "📦", "merged": "✅",
        "conflict": "⚠️ ", "failed": "❌"}


def show(tid):
    d = api.get(f"/tasks/{tid}").json()
    t = d["task"]
    print(f"\nЗадача {t['id']} [{t['status']}]  стоимость ≈ ${d['total_cost']:.2f}")
    if t["error"]:
        print("  ошибка:", t["error"][:300])
    for s in d["subtasks"]:
        print(f"  {ICON.get(s['status'], '?')} {s['key']:<10} {s['status']:<10} "
              f"{(s['worker'] or '-'):<9} {s['title']}")
    return t["status"]


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("submit")
    s.add_argument("prompt")
    s.add_argument("--repo", required=True)
    s.add_argument("--base", default="main")
    s.add_argument("--test", default="")

    for name in ("status", "watch"):
        x = sp.add_parser(name)
        x.add_argument("id")
    sp.add_parser("workers")

    a = p.parse_args()
    if a.cmd == "submit":
        tid = api.post("/tasks", json={"prompt": a.prompt, "repo": a.repo,
                                        "base": a.base, "test_cmd": a.test}).json()["id"]
        print("создана задача", tid)
    elif a.cmd == "status":
        show(a.id)
    elif a.cmd == "watch":
        while show(a.id) not in ("done", "failed"):
            time.sleep(5)
    elif a.cmd == "workers":
        for w in api.get("/workers").json():
            age = time.time() - w["last_seen"]
            print(f"{w['id']}  {w['name']:<12} слотов={w['slots']}  "
                  f"{'online' if age < 60 else f'offline {int(age)}с'}")


if __name__ == "__main__":
    sys.exit(main())
```

---

## 11. Развёртывание

### Сеть

Самый простой вариант — **Tailscale** (или WireGuard): все устройства получают приватные адреса, координатор слушает только на tailnet-адресе. Воркерам не нужны входящие порты.

### Git remote

Любой, доступный всем машинам (SSH-ключи / deploy-токен с правом push в `ccd/*`). Для личного использования достаточно bare-репозитория на сервере или приватного репозитория на GitHub.

### Координатор (systemd)

`/etc/systemd/system/ccd-server.service`:

```ini
[Unit]
Description=CCD coordinator
After=network-online.target

[Service]
User=ccd
WorkingDirectory=/opt/ccd
Environment=CCD_TOKEN=замените-на-секрет
Environment=CCD_DATA=/var/lib/ccd
ExecStart=/opt/ccd/venv/bin/uvicorn server:app --host 100.64.0.1 --port 8787
Restart=always

[Install]
WantedBy=multi-user.target
```

### Воркер (systemd user unit)

```ini
[Unit]
Description=CCD worker
After=network-online.target

[Service]
ExecStart=%h/ccd/venv/bin/python %h/ccd/worker.py %h/ccd/worker.json
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now ccd-worker
```

### Быстрый старт

```bash
# 1. координатор
python -m venv venv && ./venv/bin/pip install -r requirements.txt
CCD_TOKEN=secret ./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8787

# 2. на каждом устройстве
cp worker.example.json worker.json   # поправить server/token/slots
python worker.py worker.json

# 3. отправить задачу
export CCD_SERVER=http://100.64.0.1:8787 CCD_TOKEN=secret
python cli.py submit "Добавить JWT-авторизацию и страницу логина" \
    --repo git@github.com:me/app.git --base main --test "npm test"
python cli.py watch <id>
```

---

## 12. Безопасность

Агент с правом выполнять команды на вашем устройстве — это риск. Минимум мер:

* **Не используйте `bypassPermissions`** на личных машинах. Держите `acceptEdits` + явный `allowed_tools` (allowlist команд).
* **Изоляция воркеров:** отдельный пользователь ОС или контейнер (Docker/Podman/Firejail) для воркера; рабочая директория `~/.ccd` без доступа к личным данным.
* **Секреты:** не кладите `.env` и ключи в репозиторий; файлы окружения для тестов выдавайте воркеру отдельно (например, через `.worktreeinclude`-подход или переменные окружения сервиса).
* **Токен координатора:** длинный случайный; доступ только по приватной сети (Tailscale ACL); в продакшене — TLS и per-worker токены.
* **Prompt injection:** содержимое репозитория и зависимостей — недоверенный ввод. Ограничивайте сетевой доступ воркера, не давайте агентам выполнять произвольные `curl | sh`.
* **Git-права:** deploy-ключ только на push в `ccd/*`, защита `main` от прямых пушей.
* **Проверка `owns`** — это не только дисциплина слияния, но и защита от «вылета» агента в чужие файлы (например, CI-конфиги).
* **Ревью перед merge в `main`:** интеграционную ветку лучше вливать через PR с человеческим ревью.

---

## 13. Лимиты, стоимость, ресурсы


| Параметр  | Где задаётся                                                                          | Назначение                                                             |
| ----------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `slots`           | конфиг воркера                                                                      | сколько агентов одновременно на устройстве |
| `cpu_limit`       | конфиг воркера                                                                      | не брать новые задания при высокой загрузке |
| `max_turns`       | конфиг воркера                                                                      | потолок числа ходов агента                                |
| `timeout_s`       | конфиг воркера                                                                      | потолок времени одной подзадачи                      |
| `MAX_ATTEMPTS`    | server.py                                                                                        | число повторов подзадачи                                   |
| бюджет (v2) | флаг`--max-budget-usd`Claude Code или учёт`total_cost_usd`в координаторе | остановка при превышении                                   |

Рекомендации:

* Начинайте с **2–4 параллельных агентов** суммарно и смотрите расход квоты.
* Дорогие модели — для планировщика и интегратора, более дешёвые — для рутинных подзадач (параметр `model` в конфиге воркера, в v2 — per-subtask).
* Планировщик и VERIFY — самые «умные» шаги; не экономьте на них, это снижает число перезапусков.
* Следите, чтобы число параллельных агентов не упиралось в rate limit — при ошибках лимитов воркер должен делать backoff (в MVP это обрабатывается как retryable-ошибка).

---

## 14. Отказоустойчивость


| Сбой                                                      | Поведение                                                                                                                                 |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Воркер пропал (выключили ноутбук) | Reaper за ≤\~2 мин возвращает`running`подзадачи в`pending`, их заберёт другой воркер                |
| Агент вышел за`owns`                              | Подзадача падает с понятной ошибкой, повтор с подсказкой в промпте                         |
| Тесты не прошли                                  | Повтор с хвостом лога тестов в промпте (до`MAX_ATTEMPTS`)                                                        |
| Конфликт слияния                               | Автоматически создаётся подзадача-разрешитель                                                            |
| Перезапуск координатора                 | Состояние в SQLite сохраняется;`running`подзадачи вернёт Reaper, если воркер не отметится |
| Недоступен git remote                               | Воркер падает с retryable-ошибкой, задание вернётся в очередь                                           |
| Исчерпаны попытки                             | Подзадача и задача →`failed`с причиной в`status`                                                                        |

---

## 15. Пример сквозного сценария

**Задача:** «Добавить авторизацию: backend на JWT, форма логина во фронтенде, документация API».

1. `ccd submit ... --test "npm test"` → задача `a1b2c3d4`, статус `planning`.
2. Планировщик возвращает:
   * `A` — backend (`src/auth/**`, `tests/auth/**`), deps: —
   * `B` — UI логина (`web/src/login/**`), deps: `A`
   * `C` — документация (`docs/api/**`), deps: —
3. Сразу стартуют `A` (воркер на десктопе) и `C` (воркер на ноутбуке). `B` ждёт `A`.
4. `A` завершён → push `ccd/a1b2c3d4/A` → слит в `integration`. Теперь `B` готов: воркер на VPS создаёт worktree от свежей `integration` (с кодом `A`) и делает UI.
5. `C` и `B` слиты. При слиянии `B` случился конфликт в `package.json` → создана `B-fix1`; агент разрешил конфликт, тесты зелёные, ветка слита.
6. Создан `VERIFY`: прогон `npm test` на воркере, найден один падающий тест на стыке, агент минимально чинит.
7. Статус `done`. Ветка `ccd/a1b2c3d4/integration` готова для PR в `main`.

Вывод `ccd watch`:

```
Задача a1b2c3d4 [running]  стоимость ≈ $3.42
  ✅ A          merged     3f9a1c2d  Модуль авторизации (backend)
  🔄 B          running    7be04d11  UI формы логина
  ✅ C          merged     9a77e2f0  Документация API
```

---

## 16. Roadmap

**v1 — MVP (этот документ)**

* очередь, воркеры, worktree, git-слияние, авто-разрешение конфликтов, VERIFY

**v2 — устойчивость и контроль**

* повторное планирование при невалидном плане (с текстом ошибки);
* бюджет на задачу, остановка при превышении, backoff на rate limit;
* метки воркеров (`labels`) и требования подзадач (`needs: ["gpu", "docker"]`);
* per-subtask модель (дешёвая/дорогая);
* логи агентов (стрим `--output-format stream-json`) и просмотр в CLI;
* создание PR (`gh pr create`) по завершении.

**v3 — удобство**

* веб-панель (статусы, стоимость, логи, ручной retry/cancel);
* уведомления (Telegram/Slack);
* динамическое перепланирование: агент может запросить новую подзадачу;
* переход на **Agent SDK** вместо `claude -p` для тонкого контроля (хуки, потоковые события, кастомные инструменты);
* обмен сообщениями между агентами (общая «доска» заметок, cross-session messaging);
* кэш зависимостей/сборок между воркерами (`node_modules`, build cache).

**v4 — масштаб**

* Postgres вместо SQLite, несколько координаторов;
* запуск воркеров в одноразовых контейнерах/VM (эфемерные среды);
* политики очередей, приоритеты, квоты по проектам.

---

## 17. Что проверить перед использованием

1. **Флаги CLI.** Названия и поведение флагов (`--output-format json`, `--max-turns`, `--allowedTools`, `--permission-mode`, `--model`, `--worktree`, `--max-budget-usd`) и поля JSON-ответа (`result`, `is_error`, `total_cost_usd`) зависят от версии Claude Code. Сверьтесь с `claude --help` и официальной документацией на `code.claude.com`.
2. **Условия использования и лимиты** вашего тарифа/аккаунта для параллельных и автоматизированных запусков на нескольких устройствах.
3. **Права доступа** воркеров к репозиторию и политика защиты веток.
4. **Качество декомпозиции** на вашем реальном проекте: начните с небольших задач и оцените долю подзадач, которые сливаются без конфликтов.
5. **Безопасность воркеров** (раздел 12) — прежде чем подключать основной рабочий компьютер.

> MVP-код — отправная точка: он намеренно прост (SQLite, один координатор, опрос вместо WebSocket). Его достаточно, чтобы проверить идею на 2–3 устройствах и реальных задачах, а затем развивать по roadmap.
>
