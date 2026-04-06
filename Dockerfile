# Stage 1: Build frontend dashboard
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci --no-audit
COPY dashboard/ .
RUN npm run build

# Stage 2: Install Python dependencies (cached layer)
FROM python:3.11-slim AS deps

WORKDIR /app

# Install system dependencies for TA-Lib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    wget \
    && wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib/ \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
    && apt-get purge -y gcc g++ make wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Final runtime image (smallest possible)
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy TA-Lib shared libraries from deps stage
COPY --from=deps /usr/lib/libta_lib* /usr/lib/
COPY --from=deps /usr/include/ta-lib /usr/include/ta-lib

# Install only runtime system deps (curl/wget for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl wget \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Copy built frontend from stage 1
COPY --from=frontend /frontend/dist /app/dashboard_dist

# Create non-root user
RUN useradd -m -r appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app
USER appuser

# Environment defaults for structured logging
ENV LOG_FORMAT=json \
    LOG_LEVEL=INFO

EXPOSE 8001

CMD ["uvicorn", "mcp_server.mcp_server:app", "--host", "0.0.0.0", "--port", "8001"]
