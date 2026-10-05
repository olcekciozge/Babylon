# Babylon Chat

A real-time chat room built with FastAPI and WebSockets.

## Features
- Real-time messaging between multiple browser clients
- Usernames and join/leave notifications
- Connection manager that broadcasts messages to all users

## Tech Stack
- Python, FastAPI, Uvicorn
- Vanilla HTML/JavaScript (browser WebSocket API)

## Run Locally
```bash
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Then open http://localhost:8000 in two browser tabs.
