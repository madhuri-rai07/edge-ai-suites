# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

FROM python:3.12-slim

ARG USER_ID=1000
ARG USER_GROUP_ID=1000

# Install system dependencies first
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy pyproject.toml first for dependency installation
COPY pyproject.toml /app/

# Upgrade pip and install dependencies directly from pyproject.toml
RUN pip install uv && uv sync
# Copy the rest of the application
COPY . /app/

# Create non-root user and change ownership
RUN groupadd -g ${USER_GROUP_ID} routeuser && \
    useradd -m -s /bin/bash -u ${USER_ID} -g ${USER_GROUP_ID} routeuser && \
    chown -R routeuser:routeuser /app

USER routeuser

# Expose port for Gradio interface
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD uv run python health_check.py 7860 || exit 1

# Run the application
CMD ["uv", "run", "python", "main.py"]