FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better Docker caching)

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy only the backend code

COPY backend/ ./backend

WORKDIR /app/backend

EXPOSE 5000

CMD ["python", "app.py"]
