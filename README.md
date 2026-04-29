# CMR → RMPD App

Веб-додаток для логістів: завантаж фото CMR — отримай готові дані для RMPD.

---

## Деплой на Railway (безкоштовно, ~10 хвилин)

### 1. GitHub
1. Зайди на https://github.com і створи акаунт (якщо немає)
2. Натисни "New repository" → назви `cmr-rmpd` → Create
3. Завантаж всі файли цієї папки в репозиторій

### 2. Railway
1. Зайди на https://railway.app
2. "Login with GitHub"
3. "New Project" → "Deploy from GitHub repo" → вибери `cmr-rmpd`
4. Railway автоматично знайде `Procfile` і задеплоїть

### 3. Anthropic API Key
1. Зайди на https://console.anthropic.com → API Keys → Create Key
2. В Railway: відкрий свій проект → Variables → додай:
   - `ANTHROPIC_API_KEY` = твій ключ

### 4. Готово
Railway дасть URL виду `https://cmr-rmpd-xxx.railway.app`
Відкрий його — додаток працює.

---

## Структура файлів

```
cmr-app/
├── app.py              # Backend (Flask)
├── requirements.txt    # Залежності Python
├── Procfile            # Команда запуску для Railway
└── static/
    └── index.html      # Frontend для логістів
```

---

## Локальний запуск (для тесту)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python app.py
```

Відкрий http://localhost:5000
