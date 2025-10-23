FROM python:3.15-rc-alpine as base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apk add gcc musl-dev ffmpeg libffi-dev --no-cache

ENV UV_PROJECT_ENVIRONMENT="/usr/local/"

WORKDIR /home/bot

COPY main.py .
COPY pyproject.toml .
COPY uv.lock .

RUN uv sync --locked

