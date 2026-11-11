FROM python:3.13-slim
WORKDIR /app
# ffmpeg: qo'shiq namunasini (20 s) kesish uchun
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "app.main"]
