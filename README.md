# telemost-pyrus-bot

Бот для мессенджера Яндекс Телемоста: пересланное ему сообщение превращается в задачу Pyrus.
Тема — первая строка текста, инициатор — автор пересланного сообщения, вложения переносятся в задачу.

```bash
cp .env.example .env   # заполнить токены
docker compose up -d --build
```

Проверка: `python3 test_bot.py`
# telemost-pyrus-bot
