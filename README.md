# LocalScript

## Быстрый старт (Docker)

### Требования

- [Docker](https://docs.docker.com/get-docker/) и Docker Compose v2+
- Для GPU-ускорения на Linux/Windows: драйверы NVIDIA и [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### Запуск

```bash
# Автоматическое определение GPU (рекомендуется)
./run.sh

# Явно без GPU (CPU-режим)
docker compose up --build

# Явно с NVIDIA GPU (Linux / Windows WSL2)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

При первом запуске автоматически скачивается модель `qwen2.5-coder:7b-instruct-q6_K` (~5 ГБ). Приложение ждёт окончания загрузки и выводит прогресс в логи.

После запуска API доступен по адресу: `http://localhost:8000`

### macOS (Apple Silicon)

Docker не имеет доступа к Metal/MPS внутри контейнера. Для использования GPU запустите Ollama нативно:

```bash
brew install ollama
ollama serve  # в отдельном терминале

# Запустить только приложение, указав на нативный Ollama
OLLAMA_HOST=http://host.docker.internal:11434 docker compose up app --build
```

Данные моделей Ollama хранятся в именованном Docker-томе `ollama_models` и сохраняются между перезапусками.

---

## API

Swagger UI доступен по адресу: `http://localhost:8000/docs`

### POST /generate

Генерирует Lua-код по описанию задачи. Поддерживает многоходовой диалог — если агенту нужна уточняющая информация, он вернёт вопрос в поле `question`. Ответ на вопрос отправляется следующим запросом с тем же `session_id`.

**Тело запроса:**

```json
{
  "content": "Описание задачи или ответ на вопрос агента",
  "session_id": "optional-session-id",
  "wf_context": {"wf": {"vars": {"price": 100}}},
  "existing_code": "lua{return wf.vars.price * 2}lua"
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `content` | `string` | Текст запроса или ответ на уточняющий вопрос |
| `session_id` | `string?` | ID сессии для продолжения диалога. Если не указан — создаётся новая сессия |
| `wf_context` | `object?` | JSON-контекст переменных (`wf.vars` / `wf.initVariables`). Передаётся напрямую в граф, минуя LLM-извлечение |
| `existing_code` | `string?` | Существующий Lua-скрипт в формате `lua{...}lua`. Обёртка снимается автоматически перед передачей в граф |

**Ответ:**

```json
{
  "session_id": "abc123",
  "question": null,
  "result": {
    "total": "lua{return wf.vars.price * wf.vars.quantity}lua"
  },
  "debug": null
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `session_id` | `string` | ID сессии — передавать в следующих запросах |
| `question` | `string?` | Уточняющий вопрос от агента. Если задан — `result` будет `null` |
| `result` | `object?` | Готовый результат: объект вида `{"ключ": "lua{...}lua"}`. Если задан — `question` будет `null` |
| `debug` | `object?` | Отладочная информация. Присутствует только при `LOCALSCRIPT_DEBUG=1` |
| `debug.raw_code` | `string` | Сгенерированный Lua-код без обёртки |
| `debug.static_result` | `object?` | Результат статической проверки (luacheck) |
| `debug.dynamic_result` | `object?` | Результат динамического запуска кода |

### Пример использования

**Запрос с контекстом переменных:**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Умножить wf.vars.price на wf.vars.quantity и записать результат в переменную total",
    "wf_context": {"wf": {"vars": {"price": 100, "quantity": 3}}}
  }'
```

**Модификация существующего кода:**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Добавь переменную с квадратом числа",
    "existing_code": "lua{return tonumber(\"5\")}lua"
  }'
```

**Многоходовой диалог:**

```bash
# 1. Первый запрос — агент задаёт уточняющий вопрос
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"content": "Обработать список заказов"}'

# Ответ: {"session_id": "abc123", "question": "Что именно нужно сделать с заказами?", "result": null}

# 2. Ответ на вопрос с тем же session_id
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"content": "Посчитать сумму всех заказов", "session_id": "abc123"}'

# Ответ: {"session_id": "abc123", "question": null, "result": {...}}
```

---

## Конфигурация

Переменные окружения:

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `OLLAMA_HOST` | `http://localhost:11434` | URL Ollama-сервера |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b-instruct-q6_K` | Модель для генерации кода |
| `LOCALSCRIPT_DEBUG` | _(не задана)_ | Если задана (любое значение) — включает DEBUG-логирование и добавляет поле `debug` в ответ API |
