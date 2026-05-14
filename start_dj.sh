#!/bin/bash

# Configuration
DJ_URL="http://localhost:8000/dj"
PORT=8000

echo "🚀 Starting Ripped Ripper DJ System..."

# 0. Pre-flight Cleanup (Kill any existing processes on port 8000)
echo "🧹 Cleaning up old processes..."
lsof -ti :$PORT | xargs kill -9 2>/dev/null
pkill -f "ngrok http $PORT" 2>/dev/null

# 1. Detect Virtual Environment
if [ -f "./.venv/bin/python" ]; then
    PYTHON_EXE="./.venv/bin/python"
elif [ -f "./venv/bin/python" ]; then
    PYTHON_EXE="./venv/bin/python"
else
    echo "❌ No virtual environment found (.venv or venv). Please create one."
    exit 1
fi

# 2. Start the Backend
echo "📡 Starting backend server..."
$PYTHON_EXE app.py &
BACKEND_PID=$!

# 3. Start Ngrok
echo "🌐 Starting Ngrok tunnel..."
ngrok http $PORT --log=stdout > /dev/null &
NGROK_PID=$!

# 4. Give them a second to warm up
sleep 3

# 5. Fetch the Ngrok URL (so you can update your HTML if it changed)
NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | jq -r '.tunnels[0].public_url')

if [ "$NGROK_URL" != "null" ]; then
    echo "✅ Tunnel Live: $NGROK_URL"
    echo "⚠️  Make sure this matches the API_BASE_URL in your HTML files!"
else
    echo "❌ Ngrok failed to start or 'jq' is not installed."
fi

# 6. Launch DJ Dashboard
echo "💻 Launching DJ Dashboard..."
open $DJ_URL

echo "--------------------------------------------------"
echo "System is running"
echo "Press CTRL+C to SHUT DOWN everything."
echo "--------------------------------------------------"

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $BACKEND_PID
    kill $NGROK_PID
    echo "✅ Done. See you next set!"
    exit
}

# Trap Ctrl+C
trap cleanup SIGINT

# Keep script running
wait
