FROM python:3.11-slim

WORKDIR /app

# 依赖缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 业务代码
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
