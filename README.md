# Архитектурный документ: CSItemStat Bot

Архитектурный документ (версия 2.0)

## 1. Назначение и ключевые функции

Приложение предоставляет пользователям Telegram статистику по предметам из инвентаря Steam. Реализовано как **монолит** на базе FastAPI.

**Функциональные возможности:**
- Загрузка списка предметов из инвентаря Steam пользователя с группировкой по `market_hash_name`.
- Отслеживание выбранных предметов: текущая минимальная цена, медиана, объём продаж, тренд.
- Графики исторических цен.
- Подписка на ежедневные/еженедельные сводки об изменении цены (процентный дайджест).
- Алерты при достижении заданного **процентного** изменения цены за 24 часа или 7 дней.
- Периодический автоматический сбор данных из Steam Web API.

---

## 2. Общая схема взаимодействия

```
Telegram Client  →  [Webhook]  →  FastAPI App  →  Telegram Bot API
                                      │
                              ┌───────┼───────┐
                              ▼               ▼
                        PostgreSQL        Redis
                              │
                              ▼
                      Steam Web API
```

- FastAPI обрабатывает входящие обновления от Telegram (webhook).
- Внутри того же процесса работает планировщик APScheduler, который периодически собирает цены и отправляет подписки.
- Redis используется как кэш инвентаря и готовых изображений графиков.

---

## 3. Технологический стек

- **Язык:** Python 3.11+
- **Веб-фреймворк:** FastAPI (uvicorn)
- **Планировщик:** APScheduler
- **База данных:** PostgreSQL 15
- **ORM:** SQLAlchemy 2.0 (асинхронный)
- **Кэш:** Redis 7 (aioredis)
- **Статистика:** pandas, numpy, scipy
- **Визуализация:** matplotlib (генерация PNG в памяти)
- **HTTP-клиенты:** httpx (для Telegram Bot API и Steam API)
- **Контейнеризация:** Docker, docker-compose

---

## 4. Структура проекта

```
steam_market_tracker/
├── app/
│   ├── main.py               # Инициализация приложения, lifespan, планировщик
│   ├── config.py             # Настройки из переменных окружения
│   ├── db/
│   │   ├── base.py           # Асинхронный движок, Base, get_session
│   │   └── models.py         # Модели SQLAlchemy
│   ├── repositories/         # Доступ к данным
│   ├── services/
│   │   ├── steam_client.py   # Обёртка Steam API (инвентарь, цены, куки, rate limit)
│   │   ├── collector.py      # Логика сбора цен и сохранения в БД
│   │   ├── inventory.py      # Получение, группировка и кэширование инвентаря
│   │   ├── statistics.py     # Расчёт трендов, процентных изменений
│   │   ├── plotter.py        # Генерация графиков
│   │   └── notifier.py       # Отправка уведомлений (дайджесты, алерты)
│   ├── bot/
│   │   ├── webhook.py        # Обработчик POST /webhook
│   │   ├── dispatcher.py     # Роутинг команд и callback-запросов
│   │   └── templates.py      # Формирование текстов и inline-клавиатур
│   └── scheduler/
│       └── jobs.py           # Задания APScheduler
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 5. Модель данных (PostgreSQL)

### 5.1 Пользователи

```sql
CREATE TABLE users (
    id          BIGINT PRIMARY KEY,        -- Telegram user_id
    chat_id     BIGINT NOT NULL,
    steam_id64  BYTEA,                     -- AES-зашифрованный SteamID64
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

### 5.2 Предметы

```sql
CREATE TABLE items (
    id               SERIAL PRIMARY KEY,
    app_id           INTEGER NOT NULL,
    market_hash_name TEXT NOT NULL,
    name             TEXT,                 -- Человекочитаемое (можно заполнять из инвентаря)
    icon_url         TEXT,
    is_tracked       BOOLEAN DEFAULT false,
    UNIQUE (app_id, market_hash_name)
);
```

### 5.3 Отслеживаемые пользователем предметы

```sql
CREATE TABLE user_tracked_items (
    user_id  BIGINT REFERENCES users(id),
    item_id  INTEGER REFERENCES items(id),
    added_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, item_id)
);
```

### 5.4 История дневных цен

```sql
CREATE TABLE item_daily_stats (
    item_id INTEGER REFERENCES items(id),
    date    DATE NOT NULL,
    price   NUMERIC(10,2) NOT NULL,       -- медианная цена (USD)
    volume  INTEGER NOT NULL,
    PRIMARY KEY (item_id, date)
);
```

### 5.5 Актуальный снапшот предмета

```sql
CREATE TABLE item_snapshot (
    item_id         INTEGER PRIMARY KEY REFERENCES items(id),
    lowest_price    NUMERIC(10,2),
    median_price    NUMERIC(10,2),
    volume_24h      INTEGER,
    price_24h_ago   NUMERIC(10,2),          -- цена сутки назад (заполняется из истории)
    trend_slope     NUMERIC(10,6),          -- наклон линейной регрессии за 7 дней
    trend_direction TEXT CHECK (trend_direction IN ('up','down','stable')),
    updated_at      TIMESTAMPTZ
);
```

### 5.6 Подписки на периодические дайджесты

```sql
CREATE TABLE subscriptions (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id),
    item_id      INTEGER NOT NULL REFERENCES items(id),
    frequency    TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly')),
    active       BOOLEAN DEFAULT true,
    last_sent_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, item_id, frequency)
);
```

### 5.7 Процентные ценовые алерты

```sql
CREATE TABLE price_alerts (
    id                 SERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES users(id),
    item_id            INTEGER NOT NULL REFERENCES items(id),
    percent_change     NUMERIC(5,2) NOT NULL,   -- 5.00 означает 5%
    period             TEXT NOT NULL CHECK (period IN ('24h', '7d')),
    active             BOOLEAN DEFAULT true,
    last_triggered_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT now()
);
```

### 5.8 Индексы

- `item_daily_stats (item_id, date DESC)` – быстрый доступ к последним точкам.
- `user_tracked_items (item_id)` – поиск пользователей, отслеживающих предмет.
- `subscriptions (active, frequency, last_sent_at)` – выборка активных подписок для дайджеста.
- `price_alerts (item_id, active)` – проверка при обновлении цены.

---

## 6. Ключевые модули и потоки данных

### 6.1 Обработка команд Telegram

**Webhook (`POST /webhook`)**  
Принимает JSON от Telegram, верифицирует секретный токен. Диспетчер определяет команду и запускает соответствующий сценарий.

**Основные команды:**

| Команда | Действие |
|--------|----------|
| `/start` | Регистрация пользователя в БД (если ещё нет). |
| `/link_steam <steam_id64>` | Привязка Steam ID, шифрование и сохранение. |
| `/inventory` | Получить список предметов инвентаря. |
| `/track <название>` | Добавить предмет в отслеживание. |
| `/untrack <название>` | Удалить из отслеживания. |
| `/stats <название>` | Сводка + график. |
| `/subscribe <название> daily\|weekly` | Подписка на дайджест. |
| `/unsubscribe <название>` | Отключение подписки. |
| `/alert <название> <процент>` | Создать алерт на изменение цены (по умолчанию за 24h). |
| `/alert <название> <процент> 7d` | Алерт за 7 дней. |
| `/alerts` | Показать свои активные алерты. |
| `/delete_alert <id>` | Удалить алерт. |

**Callback-запросы (inline-кнопки):**
- `inventory_page:<номер>` – пагинация инвентаря.
- `add_track:<item_id>` – добавить предмет из инвентаря в отслеживание.

### 6.2 Импорт инвентаря

**Сценарий:**  
1. Пользователь выполняет `/inventory`.  
2. Проверяется наличие `steam_id64` в профиле. Если отсутствует – предлагается выполнить `/link_steam`.  
3. Проверяется кэш Redis: `inv:{user_id}` (время жизни 5 минут). Если есть – берётся оттуда.  
4. Иначе вызывается `SteamClient.get_inventory(steam_id64, app_id)`.  
   - Эндпоинт: `https://steamcommunity.com/id/{steam_id64}/inventory/json/{app_id}/2`  
   - Ответ: JSON с описаниями и `market_hash_name` каждого предмета.  
5. Сервер группирует предметы по `market_hash_name`, подсчитывает количество.  
6. Для новых `market_hash_name` создаются записи в таблице `items` (если отсутствуют).  
7. Результат сохраняется в Redis на 300 секунд.  
8. Пользователю отправляется список:  
   ```
   🔹 AK-47 | Redline (Field-Tested) — 3 шт.
   🔹 M4A4 | Asiimov (Battle-Scarred) — 1 шт.
   ```
   С инлайн-кнопкой «➕ Отслеживать» под каждым предметом и кнопками навигации (по 10 предметов на странице).

**Пагинация** реализована через callback_data: `inventory_page:2`. При нажатии сервер берёт список из Redis и отправляет нужную страницу.

### 6.3 Сбор цен из Steam

**SteamClient**  
Асинхронный HTTP-клиент с куками, rate-limit (семафор 5, 20 запросов/мин). Методы:
- `get_price_overview(app_id, market_hash_name)` → lowest_price, median_price, volume (за 24h).
- `get_price_history(app_id, market_hash_name)` → массив `[date, price, volume]`.
- `get_inventory(steam_id64, app_id)` → сырой JSON инвентаря.

**Планировщик (APScheduler)**  
- **Задача `update_snapshots` (каждые 30 минут)**  
  1. Для всех предметов, у которых есть хотя бы один отслеживающий пользователь или `is_tracked = true`, выполняется запрос `price_overview`.  
  2. Обновляется `item_snapshot`. Если запись за текущий день ещё не добавлена, вставляется строка в `item_daily_stats`.  
  3. Для каждого обновлённого предмета вычисляется тренд (наклон регрессии за 7 дней).  
  4. Поле `price_24h_ago` заполняется значением цены из `item_daily_stats` за предыдущий день (если есть).  
  5. После обновления всех снапшотов запускается проверка процентных алертов (вызов `notifier.check_price_alerts`).  

- **Задача `sync_daily_history` (раз в сутки, 02:00 UTC)**  
  Для всех активных предметов запрашивается `price_history`, сохраняются недостающие дни.

- **Задача `send_digests`**  
  - **Ежедневная** (10:00): выбираются активные подписки с `frequency='daily'`.  
  - **Еженедельная** (каждый понедельник, 10:00): подписки с `frequency='weekly'`.  
  - Для каждой подписки формируется сообщение:  
    ```
    📊 Еженедельный дайджест
    AK-47 | Redline (Field-Tested)
    Текущая цена: 12.50 USD
    Изменение за неделю: ↑ 3.2%
    Тренд: восходящий
    ```
  - Отправляется пользователю через Telegram API. Обновляется `last_sent_at`.

### 6.4 Процентные алерты

При создании алерта через `/alert` сохраняется запись в `price_alerts` с указанным процентом и периодом (`24h` или `7d`).

**Проверка алертов** (встроена в конец задачи `update_snapshots`):
1. Для каждого обновлённого предмета выбираются все активные алерты.
2. Рассчитывается текущее изменение:
   - Для `24h`: `((current_price - price_24h_ago) / price_24h_ago) * 100`.
   - Для `7d`: цена 7-дневной давности извлекается из `item_daily_stats`.
3. Если модуль изменения >= `percent_change`, отправляется уведомление:  
   ```
   ⚠️ Ценовой алерт
   AK-47 | Redline (Field-Tested)
   Цена выросла на 7.2% за 24 часа
   Текущая: 12.50 USD
   ```
4. `last_triggered_at` обновляется, чтобы избежать повторных уведомлений в том же периоде (повторно сработает только при следующем обновлении, если изменение всё ещё выше порога, или после нового пересечения порога).

### 6.5 Статистические расчёты

**Модуль `statistics.py`:**
- `compute_trend(prices_array)` → slope, direction.
- `compute_percent_change(current_price, old_price)` → float.
- `get_price_days_ago(item_id, days)` – выборка из `item_daily_stats`.

### 6.6 Кэширование (Redis)

| Ключ | Содержимое | TTL |
|------|------------|-----|
| `snapshot:{item_id}` | JSON снапшота | 60 сек |
| `plot:{item_id}:{days}` | Байты PNG графика | 1 час |
| `inv:{user_id}` | Сгруппированный инвентарь | 5 мин |

### 6.7 Безопасность

- **SteamID64**: шифруется Fernet перед записью в БД, ключ в переменных окружения.
- **Steam-куки**: хранятся только в памяти (из `.env`), никогда не логируются.
- **Telegram webhook**: проверка `X-Telegram-Bot-Api-Secret-Token`.
- **База данных**: доступ только из внутренней сети docker-compose.

---

## 7. Развёртывание

`docker-compose.yml` содержит сервисы:
- `app`: FastAPI, порт 8000.
- `db`: PostgreSQL 15.
- `redis`: Redis 7-alpine.

Переменные окружения:
- `BOT_TOKEN`
- `WEBHOOK_SECRET`
- `DATABASE_URL`
- `REDIS_URL`
- `STEAM_COOKIES` (JSON-строка с куками)
- `FERNET_KEY`

---

## 8. Заключение

Документ описывает полностью готовую к реализации монолитную архитектуру сервиса отслеживания цен Steam. Все новые требования — импорт инвентаря с группировкой, подписки на периодические дайджесты и процентные ценовые алерты — интегрированы в единую кодовую базу с сохранением простоты и производительности.