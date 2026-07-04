# Build from the REPO ROOT, not from calculator/, since this image needs
# both calculator/ and the sibling sdk/ package:
#
#   docker build -f calculator/Dockerfile -t calculator:local .
#
# One image, three roles (see entrypoint.sh):
#   docker run calculator:local activity-worker   # x5, TEMPORAL_TASK_QUEUE differs
#   docker run calculator:local workflow-worker
#   docker run calculator:local starter "1 + 2"

FROM python:3.12-slim

WORKDIR /app

# Install the reusable SDK first, as its own layer - this only gets
# invalidated (and re-run) when sdk/ itself changes, not on every
# calculator/ code edit, which is the whole point of splitting it out.
COPY sdk/pyproject.toml sdk/pyproject.toml
COPY sdk/platform_sdk/ sdk/platform_sdk/
RUN pip install --no-cache-dir ./sdk

# Now the app code.
COPY calculator/ calculator/
RUN chmod +x calculator/entrypoint.sh

ENV PYTHONPATH=/app/calculator:/app/sdk \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root, per basic container hardening - K8s SecurityContext can still
# enforce this independently, but the image shouldn't rely solely on that.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# The health probe port every worker's platform_sdk.health server binds to.
EXPOSE 8080

ENTRYPOINT ["/app/calculator/entrypoint.sh"]
CMD ["activity-worker"]
