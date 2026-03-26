FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better caching)

COPY requirements.txt .
RUN pip install --upgrade pip 
&& pip install --no-cache-dir -r requirements.txt

# Copy application code

COPY backend/ ./backend
COPY models/ ./models

WORKDIR /app/backend

EXPOSE 5000

CMD ["python", "app.py"]
