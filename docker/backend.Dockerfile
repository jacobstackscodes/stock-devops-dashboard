FROM python:3.10-slim

WORKDIR /app

COPY backend/ ./backend
COPY models/ ./models
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app/backend

EXPOSE 5000

CMD ["python", "app.py"]