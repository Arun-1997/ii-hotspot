# Containerized batch runner for scheduled/server deployments.
#
#   docker build -t ii-hotspot .
#   docker run --rm ii-hotspot --selftest
#   docker run --rm -e KNMI_API_KEY \
#       -v "$PWD/data:/app/data" -v "$PWD/outputs:/app/outputs" \
#       -v "$PWD/configs:/app/configs:ro" \
#       ii-hotspot --run --config configs/pilot.toml
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[geo]"

# Data, configs, and outputs are mounted at runtime; nothing private is baked in.
VOLUME ["/app/data", "/app/outputs"]

ENTRYPOINT ["python", "-m", "ii_hotspot"]
CMD ["--demo"]
