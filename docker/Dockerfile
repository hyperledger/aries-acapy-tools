
FROM --platform=linux/amd64 python:3.10-slim AS base

WORKDIR /usr/src/app
# Install and configure poetry

ENV POETRY_VERSION=1.3.2
ENV POETRY_HOME=/opt/poetry

RUN apt-get update && apt-get install --yes curl && apt-get clean

RUN curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="/opt/poetry/bin:$PATH"
# RUN ls /opt/poetry/bin
RUN poetry config virtualenvs.in-project true

# Setup project
COPY pyproject.toml poetry.lock README.md ./
COPY acapy_wallet_upgrade/ acapy_wallet_upgrade/
COPY tests/ tests/
RUN poetry install
ENTRYPOINT . /usr/src/app/.venv/bin/activate && /bin/bash
#CMD ["/bin/bash"]
