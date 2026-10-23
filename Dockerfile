FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs

RUN pip install --no-cache-dir -e .

# Default: run the full benchmark and leave results in /app/results.
# Mount a volume there to collect the report:
#   docker run --rm -v "$PWD/results:/app/results" qdc-anomaly
ENTRYPOINT ["qdc"]
CMD ["benchmark", "--config", "configs/default.yaml"]
