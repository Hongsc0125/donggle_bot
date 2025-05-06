#!/bin/bash

echo ">>> Stopping any running main.py process..."
pkill -f "python3.12 main.py"

sleep 1
if pgrep -f "python3.12 main.py" > /dev/null; then
  echo ">>> Failed to stop bot. Process still running."
  exit 1
else
  echo ">>> Bot process stopped successfully."
fi
