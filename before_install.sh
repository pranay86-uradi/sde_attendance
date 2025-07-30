#!/bin/bash
echo "Stopping existing Flask app (if any)..."
pkill -f "python3 app.py" || true
