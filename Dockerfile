ARG PYTHON_IMAGE=python:3.12
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=on
WORKDIR /app
    # update data from apt-get repositories
RUN apt-get update && \
    apt-get -y install unzip curl gnupg wget

# sql server drivers and bcp
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/trusted.gpg.d/microsoft.gpg && \
    curl -fsSL https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 mssql-tools18 unixodbc-dev libgssapi-krb5-2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/mssql-tools18/bin:${PATH}"

# COPY backend/requirements.txt ./requirements.txt
# (Optional) install build deps only if wheels need compiling; kept minimal for lean image
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip
COPY backend ./backend
COPY static ./static

# Static frontend served from / (index) and /static assets. React build removed; 'frontend' folder deprecated.
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]