#!/bin/sh

# Initialize/Seed the database
echo "Seeding database..."
python seed.py

# Start the server
echo "Starting server..."
exec gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
