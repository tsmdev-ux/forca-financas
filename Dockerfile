FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY forca ./forca

RUN useradd --create-home --uid 1000 forca && mkdir /data && chown forca /data
USER forca
ENV FORCA_DATA_DIR=/data FORCA_HOST=0.0.0.0 FORCA_PORT=8000 HOME=/home/forca

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/manifest.webmanifest', timeout=3)"

CMD ["python", "-m", "forca.main"]
