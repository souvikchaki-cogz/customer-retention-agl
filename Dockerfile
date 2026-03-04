# Use official Python image
ARG PYTHON_IMAGE=python:3.12
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=on

WORKDIR /app

# Install system dependencies for SQL Server
RUN apt-get update && \
    apt-get -y install unzip curl gnupg wget

# SQL Server drivers and bcp
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/trusted.gpg.d/microsoft.gpg && \
    curl -fsSL https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 mssql-tools18 unixodbc-dev libgssapi-krb5-2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/mssql-tools18/bin:${PATH}"

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

# Copy all app code (webapp, shared, static, plus anything you need)
COPY shared ./shared
COPY webapp/app ./webapp/app
COPY webapp/static ./webapp/static

# Optionally copy frontend JS/CSS/HTML if your client is served from FastAPI/static
# COPY webapp/frontend ./webapp/frontend

EXPOSE 8000
# Main FastAPI entry point. Adjust if your filename/ASGI app path differs!
CMD ["uvicorn", "webapp.app.main:app", "--host", "0.0.0.0", "--port", "8000"]