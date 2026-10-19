FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GUARDBENCH_DB=/app/data/guardbench.sqlite3
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && useradd --create-home app && mkdir -p /app/data /app/artifacts && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["guardbench", "serve", "--host", "0.0.0.0", "--port", "8000"]
