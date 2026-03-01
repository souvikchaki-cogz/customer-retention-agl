ARG PYTHON_IMAGE=python:3.12
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=on
WORKDIR /app

# Install ODBC drivers for pyodbc / Azure SQL
RUN apt-get update && apt-get install -y \
    curl gnupg unixodbc-dev odbcinst \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --output /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY webapp ./webapp

EXPOSE 8000
CMD ["uvicorn", "webapp.app.main:app", "--host", "0.0.0.0", "--port", "8000"]