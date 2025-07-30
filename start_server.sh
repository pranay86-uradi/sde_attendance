#!/bin/bash
cd /home/ec2-user/myapp
echo "Starting Flask app..."
nohup python3 app.py > app.log 2>&1 &
