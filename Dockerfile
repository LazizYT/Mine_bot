FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Тесты гоняются при каждой сборке: сломанный код не доедет до деплоя.
# Dummy env только на время сборки (config.py требует TELEGRAM_TOKEN при импорте).
# Тесты используют отдельную временную БД (tests/platform_base.py), продакшен-данные не трогаются.
RUN TELEGRAM_TOKEN=123456:TEST-DUMMY-TOKEN-FOR-BUILD GROQ_API_KEY=test GEMINI_KEY=test python -m unittest discover -s tests -p "test_*.py"

CMD ["python", "launcher.py"]
