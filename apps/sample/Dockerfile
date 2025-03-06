#
# BUILDER
# This is where the app is built and dependencies are installed
#
ARG PYTHON_VERSION=3.12.9

FROM python:${PYTHON_VERSION}-slim-bookworm AS build
ARG APP="fraud"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install required packages
RUN apt update && apt upgrade -y
RUN apt install -y git

# Setup UV environment variables
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python${PYTHON_VERSION}

WORKDIR /app

# Copy separately as it's a dependency for packages in core
COPY packages /app/packages

RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --package=${APP}

COPY apps /app/apps

# For testing and linting purposes ensure the following files are copied
COPY pytest.ini /app/pytest.ini
COPY pyproject.toml /app/pyproject.toml

# At this point we can now run tests and linting if required


FROM build AS after-build
WORKDIR /app

# Clean up the build environment
RUN rm pytest.ini
RUN rm pyproject.toml
RUN rm -rf $(find . -type d -name tests)
RUN rm -rf $(find /app/apps -mindepth 1 -maxdepth 1 ! -name ${APP})

# Install the app in production mode
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --package=${APP}

#
# PRODUCTION
# This is slimmed down and only includes what is essentially required for the app to run in production
#
FROM python:${PYTHON_VERSION}-slim-bookworm AS prod
ARG APP="fraud"
ARG BUILD_DATE

# Install required packages
RUN apt update && apt upgrade -y
RUN apt install -y curl 

# Install NodeJS and PM2 - a process manager (optional) - Nope
# RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
# RUN apt install -y nodejs
# RUN npm install -g pm2

# Clean up apt and temporary files
RUN apt clean
RUN rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    BUILD_DATE=${BUILD_DATE}

# Setup user and group
RUN addgroup --system --gid 1001 app
RUN adduser --system --uid 1001 app

COPY --from=after-build --chown=app:app /app /app

# Set the working directory to the app folder
WORKDIR /app/apps/${APP}

# Create a data folder and set permissions (this ensures that if we mount a volume the permissions are correct)
RUN mkdir /app/apps/${APP}/data
RUN chown -R app:app /app/apps/${APP}/data

# Switch to the app user
USER app:app

EXPOSE 8000
CMD ["fastapi", "run", "fraud/internal_server.py", "--proxy-headers", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

