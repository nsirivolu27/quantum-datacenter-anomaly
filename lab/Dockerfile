FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml README.md LICENSE ./
RUN python -c "import subprocess,tomllib; subprocess.check_call(['pip','install','--no-cache-dir',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])"
COPY src ./src
# Use the project's existing dependencies. No quantum training runs in the lab.
RUN pip install --no-cache-dir --no-deps .
COPY lab/settings.json ./lab/settings.json
ENTRYPOINT ["python", "-m", "qdc_anomaly.lab"]
