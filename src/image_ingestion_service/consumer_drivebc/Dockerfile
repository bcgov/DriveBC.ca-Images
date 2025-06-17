FROM python:3.12-slim
# Install required system packages including fonts
RUN apt-get update && apt-get install -y fonts-dejavu-core
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

CMD ["python", "-u", "app/main.py"]

