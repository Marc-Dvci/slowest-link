# Two images from one file; compose.yaml builds both, and a plain `docker build .` gives the web page.
#   cli  the command line on the committed plan:  docker run --rm slowest-link:cli check
#   web  the browser page, served on port 8080 (Relate runs in the page, in WebAssembly)

FROM python:3.12-slim-bookworm AS cli
ENV PYTHONUNBUFFERED=1 \
    DO_NOT_TRACK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY slowest_link/ slowest_link/
COPY sources/ sources/
COPY plan/ plan/
COPY evidence/ evidence/
COPY experiments/ experiments/
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
ENTRYPOINT ["python", "-m", "slowest_link"]
CMD ["check"]

FROM cli AS web
COPY --chown=appuser web/ web/
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/', timeout=4)"
ENTRYPOINT ["python", "-m", "http.server", "8080", "--bind", "0.0.0.0", "--directory", "web"]
CMD []
