# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Update package list and install OpenSCAD and other dependencies
RUN apt-get update && \
    apt-get install -y \
    openscad \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /tmp/uploads

# Expose port (Railway will set PORT environment variable)
EXPOSE 5002

# Run the application
CMD ["python", "app.py"]