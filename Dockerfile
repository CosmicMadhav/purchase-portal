FROM python:3.13-slim

# LibreOffice makes the PDFs inside the container; Liberation fonts have the same metrics as
# Times New Roman / Arial, Carlito matches Calibri, so the layout stays as in Word.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui \
        fonts-liberation fonts-liberation2 fonts-crosextra-carlito fonts-dejavu-core fonts-symbola \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV HOST=0.0.0.0 PORT=5050 NO_BROWSER=1 OUTPUT_DIR=/app/data/output PYTHONUNBUFFERED=1
EXPOSE 5050
VOLUME /app/data
CMD ["python", "app.py"]
