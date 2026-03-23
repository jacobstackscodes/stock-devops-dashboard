FROM python:3.10-slim

WORKDIR /app

COPY worker/ ./worker
COPY requirements.txt .

RUN apt-get update && apt-get install -y cron

RUN pip install --no-cache-dir -r requirements.txt

COPY docker/cronjob /etc/cron.d/stock-cron

RUN chmod 0644 /etc/cron.d/stock-cron
RUN crontab /etc/cron.d/stock-cron

CMD ["cron", "-f"]