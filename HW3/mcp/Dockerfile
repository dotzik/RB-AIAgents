# Build context je kořen repozitáře (RB-AIAgents/), ne tenhle adresář —
# image potřebuje sáhnout do HW1/ pro balíček s nástroji.
#   docker build -f HW3/mcp/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY HW3/mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# `--no-deps` je zároveň test směru závislostí: `tools.py` ani `db.py`
# neimportují nic z LLM světa. Kdyby se to porušilo, image spadne na ImportError.
COPY HW1/pyproject.toml HW1/README.md ./hw1/
COPY HW1/src ./hw1/src
RUN pip install --no-cache-dir --no-deps ./hw1

COPY HW3/mcp/src ./src
ENV PYTHONPATH=/app/src

# Databáze se mountuje read-only jako jediný soubor; cestu drží compose.
ENV TIMEAGENT_DB=/data/timeagent.sqlite

EXPOSE 8000
CMD ["uvicorn", "timeagent_mcp.server:app", "--host", "0.0.0.0", "--port", "8000"]
