FROM python:3.10-slim

# Prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Persistent data directories (mounted via docker-compose volume)
RUN mkdir -p /data/images

# Expose the port
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["./entrypoint.sh"]
