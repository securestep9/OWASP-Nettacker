### Multi-stage Dockerfile 
### Build stage
FROM python:3.11.11-slim AS builder 
### Install OS dependencies and poetry package manager
RUN apt-get update && \
    apt-get install -y gcc libssl-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip poetry

WORKDIR /usr/src/owaspnettacker

COPY nettacker nettacker
COPY nettacker.py poetry.lock pyproject.toml README.md ./

### 1. Configure poetry to create virtualenvs inside the working folder
### 2. Install Nettacker using Poetry
### 3. Use poetry 'build' to package the project into distributable formats
RUN poetry config virtualenvs.in-project true && \
    poetry install --no-cache --no-root --without dev --without test && \
    poetry build

### Runtime stage - start from a clean Python image
FROM python:3.11.11-slim AS runtime
WORKDIR /usr/src/owaspnettacker

### Bring from 'builder' just the virtualenv and the packaged Nettacker as a wheel 
COPY --from=builder /usr/src/owaspnettacker/.venv ./.venv
COPY --from=builder /usr/src/owaspnettacker/dist/*.whl .

ENV PATH=/usr/src/owaspnettacker/.venv/bin:$PATH
### Use pip inside the venv to install the wheel
RUN ./.venv/bin/pip install nettacker-*.whl

### We now have Nettacker installed in the virtualenv with 'nettacker' command whic his the new Entrypoint
ENV docker_env=true
ENTRYPOINT [ "nettacker" ]
CMD ["-h"]
