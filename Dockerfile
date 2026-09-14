FROM python:3.12.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY main.py config.py calendar_service.py sheets_service.py database.py line_service.py ./
COPY booking_rules.py date_parser.py booking_actions.py booking_view.py async_services.py notifications.py waitlist_service.py ./
RUN useradd --uid 10001 --create-home app && chown app /app
USER app
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
