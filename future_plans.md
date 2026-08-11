# 🚀 TASK: Smart Content Storage, Auto-Publishing & Channel Network Management

Ты работаешь над существующим Telegram-проектом с системой **Smart Queue**. Не переписывай проект с нуля. Сначала изучи существующую архитектуру, найди текущую реализацию Smart Queue, каналов, постов, базы данных и админ-панели, затем аккуратно расширь её.

Главная цель обновления:

> Превратить Smart Queue в полноценную систему хранения, планирования и автоматической публикации контента, а также добавить удобное управление сетью однотипных Telegram-каналов через единую админ-панель.

---

# 1. 🗄️ CONTENT STORAGE — ЕДИНОЕ ХРАНИЛИЩЕ ПОСТОВ

Создай отдельное постоянное хранилище для всех постов, которые проходят через Smart Queue.

Каждый пост, добавленный в Smart Queue, должен автоматически попадать в Content Storage.

## Для каждого поста хранить:

* `id`
* `source`
* `source_url`
* `original_message_id`
* `original_channel_id`
* `title`
* `text`
* `media`
* `media_type`
* `caption`
* `hashtags`
* `category`
* `language`
* `created_at`
* `updated_at`
* `status`
* `priority`
* `is_used`
* `usage_count`
* `last_used_at`
* `times_published`
* `published_channels`
* `tags`
* `content_hash`

## Возможные статусы:

* `draft`
* `queued`
* `available`
* `scheduled`
* `publishing`
* `published`
* `archived`
* `disabled`
* `failed`

---

# 2. 🧠 SMART QUEUE → STORAGE

Измени существующую Smart Queue:

Когда пользователь добавляет пост через Smart Queue:

1. Валидировать пост.
2. Обработать текст/media.
3. Сохранить его в Content Storage.
4. Создать запись в очереди.
5. Указать приоритет.
6. Добавить категорию и теги.
7. Не удалять пост после публикации.
8. Пост должен оставаться доступным для повторного использования.

Важно:

**Smart Queue и Content Storage — разные сущности.**

Smart Queue отвечает за текущую очередь обработки.

Content Storage отвечает за долговременное хранение контента.

Один и тот же пост может:

* попасть в очередь;
* быть опубликован;
* снова использоваться позже;
* публиковаться в разных каналах;
* иметь разные статусы для разных каналов.

---

# 3. 🔄 CONTENT REUSE

Добавь возможность повторного использования постов.

Администратор должен иметь настройки:

### Reuse mode

* `Never reuse`
* `Reuse after X days`
* `Unlimited reuse`

Например:

Пост был опубликован в `Channel A`.

Он не должен сразу снова попасть в `Channel A`.

Но его можно использовать:

* через 3 дня;
* в `Channel B`;
* в `Channel C`;
* или повторно в том же канале через заданный интервал.

Добавь защиту от слишком частого повторения одного и того же контента.

---

# 4. 📡 CHANNEL AUTO-PUBLISHING

Для каждого Telegram-канала должна существовать собственная конфигурация автоматической публикации.

Пример:

```text
Channel: Minecraft Mods RU

Status: ACTIVE

Publishing:
Every 6 hours

Content source:
Content Storage

Selection:
Random

Category:
Minecraft Mods

Minimum delay:
6 hours

Reuse:
After 7 days
```

---

# 5. ⏰ ГИБКОЕ РАСПИСАНИЕ

Для каждого канала поддержать:

### Интервал

* каждые 15 минут
* 30 минут
* 1 час
* 2 часа
* 3 часа
* 6 часов
* 12 часов
* 24 часа

### Custom interval

Позволить указать:

```text
Every X hours
Every X minutes
```

### Cron

Для продвинутого режима поддержать cron-расписание.

Например:

```text
0 */6 * * *
```

или

```text
0 12 * * *
```

---

# 6. 🎲 ВЫБОР ПОСТА

Добавь несколько алгоритмов выбора контента.

## Random

Полностью случайный пост.

## Random Weighted

Случайный выбор с учётом веса.

Например:

```text
Priority 1 → 10%
Priority 5 → 50%
Priority 10 → 90%
```

## FIFO

Сначала самые старые доступные посты.

## LIFO

Сначала самые новые.

## Least Used

Выбирать пост, который использовался меньше всего.

## Category Rotation

Чередовать категории:

```text
Mods
→
Shaders
→
News
→
Textures
→
Mods
→
Shaders
```

## Smart Selection

Интеллектуальный алгоритм:

* учитывать категорию канала;
* учитывать историю публикаций;
* избегать повторов;
* учитывать популярность;
* учитывать priority;
* учитывать freshness;
* учитывать tags.

---

# 7. 🎯 ФИЛЬТРЫ КОНТЕНТА

Для каждого канала можно указать:

### Categories

```text
Mods
Textures
Shaders
News
Tutorials
Memes
```

### Tags

```text
minecraft
forge
fabric
1.21
1.21.8
optimization
```

### Languages

```text
ru
uz
en
```

### Sources

Например:

```text
CurseForge
Modrinth
Telegram
Manual
AI Generated
```

Канал должен получать только контент, соответствующий его фильтрам.

---

# 8. 🌐 CHANNEL NETWORKS

Это одна из главных новых функций.

Создай сущность:

```text
Channel Group / Network
```

Например:

```text
Minecraft Network
```

В неё входят:

```text
Minecraft RU
Minecraft UZ
Minecraft EN
Minecraft Mods
Minecraft News
Minecraft Memes
```

---

# 9. ⚡ MASS CHANNEL MANAGEMENT

Если несколько каналов используют одинаковые настройки, администратор должен иметь возможность управлять ими одновременно.

Например:

```text
Select:

☑ Minecraft RU
☑ Minecraft UZ
☑ Minecraft EN
☑ Minecraft Mods
☑ Minecraft News
```

После этого:

### Bulk Actions

* Enable
* Disable
* Pause publishing
* Resume publishing
* Change interval
* Change posting mode
* Change category
* Change language
* Change reuse period
* Change source
* Change template
* Change timezone
* Copy settings
* Reset settings
* Delete from network

---

# 10. 📋 CHANNEL TEMPLATES

Создай систему шаблонов.

Например:

```text
Template:
Minecraft News Channel

Publishing:
Every 6 hours

Selection:
Random Weighted

Categories:
News, Updates

Language:
RU

Reuse:
7 days

Post Template:
{title}

{description}

🔗 {link}

#Minecraft
```

После создания шаблона можно применить его сразу к 10, 50 или 100 каналам.

---

# 11. 📋 CLONING CHANNEL SETTINGS

Добавь:

```text
Clone settings
```

Например:

```text
Minecraft RU
      ↓
Clone configuration
      ↓
Minecraft UZ
```

Копируются:

* расписание;
* алгоритм выбора;
* фильтры;
* шаблон;
* настройки повторного использования;
* категории;
* теги;
* timezone;
* media settings.

При этом уникальные параметры канала:

* channel ID;
* username;
* title;

не копируются.

---

# 12. 🧩 CHANNEL CONFIGURATION

Для каждого канала создать отдельную страницу настроек.

## General

* Channel name
* Channel ID
* Username
* Active / Disabled
* Network
* Description

## Publishing

* Auto publish ON/OFF
* Interval
* Cron
* Timezone
* Start time
* End time
* Max posts per day

## Content

* Selection algorithm
* Categories
* Tags
* Languages
* Sources
* Reuse policy

## Formatting

* Post template
* Prefix
* Suffix
* Hashtags
* Link preview
* Media settings

## Safety

* Duplicate protection
* Flood protection
* Failed retry count
* Cooldown
* Rate limits

---

# 13. 📊 ADMIN DASHBOARD

Создай полноценную админ-панель.

Главная страница должна показывать практически всё важное в одном месте.

## Dashboard

Показывать:

```text
Total Channels
Active Channels
Paused Channels
Total Posts
Available Posts
Scheduled Posts
Published Today
Failed Posts
Queue Size
Storage Size
```

---

# 14. 📈 ANALYTICS

Добавь статистику.

### Posts

* всего постов;
* опубликовано;
* ожидает публикации;
* failed;
* archived;
* most used;
* least used.

### Channels

* количество публикаций;
* успешные публикации;
* ошибки;
* последнее сообщение;
* следующая публикация.

### Network

Для каждой сети:

```text
Network
├── Channels
├── Posts
├── Publications
├── Errors
└── Activity
```

---

# 15. 📅 PUBLICATION CALENDAR

Создай календарь публикаций.

На нём должно быть видно:

```text
10:00  → Minecraft RU → Post #123
12:00  → Minecraft UZ → Post #456
14:00  → Minecraft EN → Post #789
16:00  → Minecraft RU → Post #222
```

Добавить:

* day view;
* week view;
* month view.

---

# 16. 📜 PUBLICATION HISTORY

Создай историю всех публикаций.

Для каждой публикации:

```text
Publication ID
Post ID
Channel
Network
Published At
Status
Error
Retry Count
Message ID
```

Статусы:

```text
SUCCESS
FAILED
RETRYING
SKIPPED
CANCELLED
```

---

# 17. ❌ ERROR MANAGEMENT

Если публикация не удалась:

1. Записать ошибку.
2. Сохранить stack/error message.
3. Увеличить retry counter.
4. Повторить публикацию по настройке.
5. После максимального количества попыток отправить в Failed.
6. Показать проблему в админ-панели.

Добавить кнопку:

```text
Retry
```

и

```text
Retry All Failed
```

---

# 18. 🧪 PREVIEW

Перед публикацией администратор должен иметь возможность увидеть:

```text
Preview Post
```

То есть Telegram-подобный preview:

* текст;
* изображение;
* видео;
* caption;
* buttons;
* links.

---

# 19. ✏️ POST MANAGEMENT

В Content Storage добавить:

### Actions

* Edit
* Delete
* Archive
* Restore
* Duplicate
* Publish now
* Schedule
* Disable
* Change category
* Add tags
* Change priority
* View history

---

# 20. 🚀 PUBLISH NOW

Для любого поста должна быть кнопка:

```text
Publish Now
```

После нажатия:

```text
Select channels

☑ Minecraft RU
☑ Minecraft UZ
☐ Minecraft EN
```

И:

```text
Publish
```

---

# 21. 🧠 SMART DUPLICATE DETECTION

Создай защиту от дублей.

Использовать:

* `content_hash`;
* normalized text;
* media hash;
* source URL.

Если одинаковый пост уже существует:

```text
Duplicate detected
```

Но дать возможность:

```text
Add anyway
```

---

# 22. 🔐 PERMISSIONS

Если архитектура поддерживает несколько администраторов, добавь роли:

```text
Owner
Admin
Editor
Viewer
```

Например:

### Owner

Полный доступ.

### Admin

Управление каналами и публикациями.

### Editor

Управление контентом.

### Viewer

Только просмотр статистики.

---

# 23. 🔔 NOTIFICATIONS

Добавь уведомления администратора:

### События

* публикация успешна;
* публикация не удалась;
* канал отключился;
* queue empty;
* storage empty;
* много ошибок;
* Telegram API error;
* scheduler error.

Настройка:

```text
Notifications ON/OFF
```

---

# 24. 🛑 EMPTY STORAGE

Если для канала нет подходящего контента:

НЕ публиковать случайный неподходящий пост.

Показать:

```text
No suitable content available.
```

И записать событие в систему.

В админ-панели:

```text
⚠ Channel X has no available content
```

---

# 25. 🔄 AUTOMATIC SCHEDULER

Создай отдельный scheduler/worker.

Он должен:

1. Проверять активные каналы.
2. Определять, кому пора публиковать.
3. Искать подходящий контент.
4. Проверять duplicate/reuse rules.
5. Выбирать пост.
6. Создавать publication job.
7. Отправлять пост.
8. Записывать результат.
9. Планировать следующую публикацию.

Не использовать блокирующие операции.

Если проект использует:

* Redis;
* Celery;
* BullMQ;
* cron;
* background workers;

используй существующую инфраструктуру вместо создания второй параллельной системы.

---

# 26. 🧱 DATABASE DESIGN

Не ломай существующую БД.

Добавь необходимые сущности примерно такого уровня:

```text
posts
content_tags
post_tags

channels
channel_settings

networks
network_channels

schedules
publications

publication_logs

templates

queue_items

system_events
```

Связи должны быть нормализованными.

Не хранить сложные структуры в одном огромном JSON, если для них нужны полноценные запросы, фильтрация или индексы.

---

# 27. ⚡ PERFORMANCE

Система должна нормально работать при:

```text
10 channels
100 channels
500 channels
1000+ channels
```

Не делать запрос к БД для каждого канала без необходимости.

Использовать:

* indexes;
* batch queries;
* caching;
* Redis;
* job queues;
* pagination;
* efficient scheduler.

Особенно оптимизировать:

```text
Find next post
Find available channels
Find due schedules
Publication history
Analytics
```

---

# 28. 🖥️ ADMIN UI

Интерфейс должен быть максимально удобным.

Основное меню:

```text
Dashboard

📦 Content Storage
├── All Posts
├── Available
├── Scheduled
├── Published
├── Failed
└── Archived

📋 Smart Queue

📡 Channels
├── All Channels
├── Active
├── Paused
└── Templates

🌐 Networks

📅 Scheduler

📊 Analytics

📜 Publication History

⚠ Errors

⚙ Settings
```

---

# 29. CHANNEL TABLE

В таблице каналов показать:

| Channel | Network | Status | Interval | Selection | Last Post | Next Post | Errors |
| ------- | ------- | ------ | -------- | --------- | --------- | --------- | ------ |

Добавить:

* search;
* filters;
* sorting;
* pagination;
* bulk selection;
* bulk actions.

---

# 30. CONTENT STORAGE TABLE

Показать:

| Post | Category | Source | Status | Uses | Last Used | Tags |
| ---- | -------- | ------ | ------ | ---- | --------- | ---- |

Добавить массовые действия:

```text
☑ Select All

Archive
Delete
Change category
Add tags
Change priority
Publish
Disable
```

---

# 31. GLOBAL SETTINGS

Добавь глобальные настройки:

```text
Default publish interval
Default selection algorithm
Default reuse period
Default timezone
Default retry count
Default retry delay
Default post template
Global rate limit
Duplicate protection
```

Настройки канала должны переопределять глобальные.

То есть:

```text
Global settings
      ↓
Network settings
      ↓
Channel settings
```

Приоритет:

```text
Channel > Network > Global
```

---

# 32. AUDIT LOG

Каждое важное действие администратора логировать:

```text
User
Action
Target
Timestamp
Old Value
New Value
IP / Session if available
```

Например:

```text
Admin changed Channel X interval
6 hours → 3 hours
```

---

# 33. API

Если проект имеет backend API, добавить endpoints для:

```text
/posts
/posts/:id
/posts/:id/publish

/queue
/queue/:id

/channels
/channels/:id
/channels/:id/settings

/networks
/networks/:id

/schedules
/publications
/publications/:id/retry

/analytics
/events
```

Добавить:

* pagination;
* filtering;
* sorting;
* validation;
* authentication;
* authorization.

---

# 34. IMPORTANT UX RULE

Не заставляй администратора настраивать 20 параметров вручную для каждого канала.

Главный сценарий должен выглядеть примерно так:

```text
Create Network
      ↓
Create Template
      ↓
Select 50 Channels
      ↓
Apply Template
      ↓
Done
```

После этого отдельный канал можно переопределить вручную.

---

# 35. NETWORK MANAGEMENT

Добавить действия для сети:

```text
Create Network
Rename
Delete
Add Channels
Remove Channels
Apply Template
Change Schedule
Pause All
Resume All
Publish Now
View Analytics
View Errors
Clone Network
```

Особенно важно:

### Pause Network

Остановить автоматическую публикацию во всех каналах сети.

При этом:

* контент не удаляется;
* расписание не удаляется;
* после Resume система продолжает работу.

---

# 36. NETWORK COPY

Добавить:

```text
Clone Network
```

Например:

```text
Minecraft RU Network
        ↓
Clone
        ↓
Minecraft UZ Network
```

Скопировать:

* templates;
* schedules;
* channel settings;
* content rules.

Но НЕ копировать:

* channel IDs;
* Telegram message IDs;
* publication history;
* errors.

---

# 37. TEST MODE

Добавить режим:

```text
TEST MODE
```

В нём scheduler работает как обычно, но публикации НЕ отправляются в реальные каналы.

Вместо этого:

```text
[TEST]

Would publish:

Post #123

to:

Minecraft RU

at:

18:00
```

Это необходимо для безопасного тестирования.

---

# 38. DRY RUN

Добавить кнопку:

```text
Run Scheduler Now
```

Она должна показать:

```text
Channels due: 12

Eligible posts:
245

Selected:
12

Skipped:
3

Reasons:
- duplicate
- no matching category
- cooldown
```

Но ничего не публиковать.

---

# 39. TIMEZONE

У каждого канала должна быть timezone.

Например:

```text
Asia/Tashkent
Europe/Moscow
Asia/Almaty
```

Все расписания должны рассчитываться с учётом timezone конкретного канала.

---

# 40. МОБИЛЬНАЯ АДАПТАЦИЯ

Админ-панель должна нормально работать на:

* Desktop
* Tablet
* Mobile

На мобильном:

* карточки вместо широких таблиц;
* быстрые действия;
* pause/resume;
* publish now;
* просмотр ошибок.

---

# 41. НЕ ЛОМАЙ СУЩЕСТВУЮЩИЕ ФУНКЦИИ

Перед изменениями:

1. Изучи проект.
2. Определи текущую архитектуру.
3. Найди Smart Queue.
4. Найди систему каналов.
5. Найди database layer.
6. Найди scheduler.
7. Найди admin panel.
8. Определи существующие API.
9. Проверь существующие tests.

После этого интегрируй новую систему в существующую архитектуру.

Не создавай дублирующие сервисы, если аналогичная функциональность уже существует.

---

# 42. MIGRATIONS

Создай безопасные database migrations.

Существующие данные НЕ должны потеряться.

После миграции:

* старые посты должны продолжить работать;
* существующие каналы должны сохраниться;
* Smart Queue должна продолжить работу;
* старые настройки должны получить default values.

---

# 43. TESTING

Создай/обнови тесты минимум для:

### Content Storage

* create post;
* update;
* delete;
* archive;
* duplicate detection.

### Scheduler

* interval;
* cron;
* timezone;
* paused channel;
* empty storage;
* random selection;
* FIFO;
* reuse rules.

### Channels

* create;
* update;
* bulk update;
* template apply;
* network pause/resume.

### Publishing

* successful publication;
* failed publication;
* retry;
* rate limit;
* duplicate protection.

### Permissions

* owner;
* admin;
* editor;
* viewer.

---

# 44. ACCEPTANCE CRITERIA

Функция считается готовой только если:

### Storage

Все посты Smart Queue автоматически сохраняются в Content Storage.

### Scheduler

Канал может автоматически получать пост каждые N часов.

### Selection

Можно выбрать:

```text
Random
FIFO
Least Used
Weighted
Smart
```

### Network

Можно управлять десятками каналов через одну группу.

### Templates

Можно создать шаблон и применить его к нескольким каналам.

### Admin

Из одной панели можно увидеть:

```text
Channels
Posts
Queue
Schedules
Publications
Errors
Analytics
Networks
```

### Safety

Нет публикации неподходящего контента.

Нет неконтролируемого спама.

Есть retry/rate-limit/duplicate protection.

---

# 45. DEVELOPMENT PROCESS

Работай поэтапно.

## Phase 1

Изучи проект и составь краткий архитектурный план.

## Phase 2

Database + migrations.

## Phase 3

Content Storage.

## Phase 4

Smart Queue integration.

## Phase 5

Scheduler.

## Phase 6

Channel settings.

## Phase 7

Networks + Templates + Bulk Management.

## Phase 8

Admin Dashboard.

## Phase 9

Analytics + Logs + Error Management.

## Phase 10

Testing + optimization.

После каждого крупного этапа запускай тесты.

---

# FINAL REQUIREMENT

Не ограничивайся созданием отдельных CRUD-страниц.

Система должна ощущаться как единая **Content Distribution Platform**:

```text
                 ┌──────────────────┐
                 │   SMART QUEUE    │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ CONTENT STORAGE  │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ SMART SELECTOR   │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │    SCHEDULER     │
                 └────────┬─────────┘
                          ↓
              ┌───────────┴───────────┐
              ↓                       ↓
       ┌─────────────┐         ┌─────────────┐
       │  NETWORK A  │         │  NETWORK B  │
       └──────┬──────┘         └──────┬──────┘
              ↓                       ↓
        ┌─────┴─────┐           ┌─────┴─────┐
        ↓     ↓     ↓           ↓     ↓     ↓
       CH1   CH2   CH3         CH4   CH5   CH6

                    ↓

              ┌──────────────┐
              │ ADMIN PANEL  │
              └──────────────┘
                    ↓
       Analytics / Logs / Errors /
       Channels / Posts / Networks /
       Scheduler / Queue / Settings
```

Главный принцип архитектуры:

**один контент → много каналов → индивидуальные правила → единое управление.**

Сделай систему масштабируемой, понятной и удобной для управления большой сетью Telegram-каналов.
