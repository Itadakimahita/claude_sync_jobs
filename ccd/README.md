# CCD — распределённый оркестратор агентов Claude Code

Одна задача → декомпозиция → параллельные агенты на разных устройствах → git-слияние → проверка.
Полное описание архитектуры: [../distributed-claude-code-orchestrator.md](../distributed-claude-code-orchestrator.md).

## Быстрый старт

```bash
python -m venv venv && ./venv/bin/pip install -r requirements.txt

# 1. координатор
CCD_TOKEN=secret ./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8787

# 2. на каждом устройстве (нужны git и claude)
cp worker.example.json worker.json     # поправить server / token / slots
./venv/bin/python worker.py worker.json

# 3. задача
export CCD_SERVER=http://127.0.0.1:8787 CCD_TOKEN=secret
./venv/bin/python cli.py submit "Добавить JWT-авторизацию" \
    --repo git@github.com:me/app.git --base main --test "npm test"
./venv/bin/python cli.py watch <id>
```

Результат — ветка `ccd/<id>/integration` в вашем remote; влейте её в `base` через PR.

## Команды CLI

`submit`, `status <id>`, `watch <id>`, `tasks`, `workers`.

## Переменные окружения координатора

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `CCD_TOKEN` | — (обязательна) | общий секрет |
| `CCD_DATA` | `./data` | SQLite и клоны репозиториев |
| `CCD_PLAN_TIMEOUT` | `900` | таймаут планировщика, сек |
| `CCD_CLAUDE` | `claude` | исполняемый файл Claude Code для планировщика |

## Заметки

* Агентам нужны права на запуск ваших тестов: добавьте их в `allowed_tools` воркера
  (например `Bash(go test:*)`). Без этого подзадача VERIFY не сможет ничего проверить.
* Конфликт слияния: воркер сам начинает `git merge` интеграционной ветки в ветку-разрешитель,
  агент убирает маркеры конфликта, воркер проверяет их отсутствие и коммитит.
* Перед использованием прочитайте разделы 12 (безопасность) и 17 (проверки) основного документа.
