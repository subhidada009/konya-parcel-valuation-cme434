FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=10000 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libexpat1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py modeling.py spatial.py ./
COPY data/ ./data/
COPY artifacts/model_card.json artifacts/model_evaluation.json artifacts/valuation_model.joblib ./artifacts/
COPY static/ ./static/
COPY templates/ ./templates/
EXPOSE 10000
CMD ["python", "app.py"]
