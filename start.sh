#!/bin/bash

echo ">>> Killing any existing main.py process..."
pkill -f "python3.12 main.py" && echo ">>> Killed existing process." || echo ">>> No existing process found."

echo ">>> Installing requirements..."
pip3.12 install -r requirements.txt

echo ">>> Starting main.py using Python 3.12 in background..."
nohup python3.12 main.py > bot.log 2>&1 &

sleep 2
if pgrep -f "python3.12 main.py" > /dev/null; then
  echo ">>> Bot successfully started in background!"
else
  echo ">>> Failed to start bot. Check bot.log for details."
  exit 1
fi
