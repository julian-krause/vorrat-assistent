FROM python:3.12-slim

# rewerse bringt die Go-Bibliothek als librewerse.so (linux/amd64) mit und lädt sie über cffi
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY tests ./tests
COPY kategorien.yml /config/kategorien.yml

RUN useradd --uid 1000 --no-create-home rewe
USER rewe
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
