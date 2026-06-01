FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CS2WEBUI_DATA_DIR=/data/panel

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "cs2webui.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
