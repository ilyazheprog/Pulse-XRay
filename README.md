
# Pulse XRay

Мониторинг и статистика для Xray/VLESS прокси с современным веб-интерфейсом.

**Внимание:** на данный момент поддерживается только протокол VLESS.

## Возможности
- Веб-панель на Flask (Python)
- Хранение настроек и истории в SQLite
- Drag&Drop, группировка, таймлайн, статистика аптайма
- Автоматическая загрузка ядра Xray при сборке контейнера
- Быстрый запуск через Docker Compose

## Быстрый старт

### 1. Клонируйте репозиторий
```
git clone ...
cd xray-stat
```

### 2. Запуск через Docker Compose
```
docker compose up -d --build
```

### 3. Откройте веб-интерфейс

Перейдите в браузере: [http://localhost:5000](http://localhost:5000)

### 4. Переменные окружения

Создайте файл `.env` (пример):
```
ADMIN_TOKEN=your_admin_token
```

### 5. Структура проекта
- `app.py` — основной Flask backend
- `core.py`, `db_utils.py` — логика и работа с БД
- `templates/` — HTML-шаблоны (Jinja2)
- `static/` — JS и CSS
- `xray-bin/xray` — ядро Xray (скачивается автоматически)
- `docker-compose.yml`, `Dockerfile` — контейнеризация

### 6. Обновление Xray

При пересборке контейнера всегда скачивается последняя версия ядра Xray.

---

## Разработка локально (без Docker)

1. Установите Python 3.11+, uv (или pip)
2. Установите зависимости:
   - `uv pip install -r requirements.txt` или `pip install -r requirements.txt`
3. Запустите: `python app.py`

---

## Лицензия
MIT
