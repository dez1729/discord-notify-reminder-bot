FROM python:3.12-slim

# set working directory inside the container
WORKDIR /app

# install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the rest of the code
COPY bot.py db.py scheduler.py roster.py ./
# run the bot
CMD ["python3", "bot.py"]

