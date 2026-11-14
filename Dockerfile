FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ngspice && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
# default: launch the dashboard; override with e.g. `docker run ... python run.py all`
CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
