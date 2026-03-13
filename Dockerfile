FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["python", "-m", "skybox_mcp.server", "sse"]
