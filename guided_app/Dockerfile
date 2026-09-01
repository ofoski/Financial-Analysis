# Build from the repo root, not this folder, since this app also
# needs xbrl_pipeline/, a sibling folder it imports directly:
#   docker build -f guided_app/Dockerfile -t guided-app .
#   docker run --gpus all -p 7860:7860 guided-app
FROM python:3.11-slim

WORKDIR /app
COPY guided_app/requirements.txt guided_app/requirements.txt
RUN pip install --no-cache-dir -r guided_app/requirements.txt

COPY xbrl_pipeline/ xbrl_pipeline/
COPY guided_app/ guided_app/

WORKDIR /app/guided_app
CMD ["python", "app.py"]
