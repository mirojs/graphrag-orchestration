FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

# Remove Yarn repository with expired GPG key to prevent apt-get update failures
# Tracking issue: https://github.com/devcontainers/images/issues/1752
RUN rm -f /etc/apt/sources.list.d/yarn.list

# Install dependencies required by GitHub Copilot's sandbox runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    bubblewrap \
    socat \
    && rm -rf /var/lib/apt/lists/*
