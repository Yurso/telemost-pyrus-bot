FROM python:3.12-slim
WORKDIR /app
COPY bot.py .
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "bot.py"]
