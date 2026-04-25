FROM python:3.11-slim

# Ghostscript install karo
RUN apt-get update && apt-get install -y \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Requirements install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Saari files copy karo
COPY . .

# HuggingFace ka port 7860 hota hai
EXPOSE 7860

# App run karo
CMD ["python", "app.py"]