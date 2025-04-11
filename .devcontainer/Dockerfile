FROM mcr.microsoft.com/devcontainers/python:1-3.13-bullseye

ENV DEBIAN_FRONTEND=noninteractive

# Upgrade packages
RUN apt-get update && apt-get -y upgrade

# Install dependencies
RUN apt-get -y install --no-install-recommends ffmpeg curl iputils-ping \
    && apt-get clean

# Update pip
RUN pip install --upgrade pip

# Install uv
RUN pip install uv
ENV UV_LINK_MODE=copy