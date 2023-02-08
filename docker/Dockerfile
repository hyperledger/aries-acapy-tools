
FROM python:3.11.1-slim AS base

WORKDIR /usr/src/app
# Install and configure poetry

ENV POETRY_VERSION=1.3.2
ENV POETRY_HOME=/opt/poetry

RUN apt-get update && apt-get install --yes curl && apt-get clean \
        && curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="/opt/poetry/bin:$PATH"
RUN ls /opt/poetry/bin
RUN poetry config virtualenvs.in-project true

# Setup project
RUN mkdir acapy_wallet_upgrade && touch acapy_wallet_upgrade/__init__.py
COPY pyproject.toml poetry.lock ./
COPY acapy_wallet_upgrade/ acapy_wallet_upgrade/
RUN poetry install