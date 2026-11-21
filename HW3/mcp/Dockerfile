# Build context je kořen repozitáře (RB-AIAgents/), ne tenhle adresář —
# image potřebuje sáhnout do HW1/ pro balíček s nástroji.
#   docker build -f HW3/mcp/Dockerfile .
# Base image digestem; aktualizace = nový digest v commitu.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

WORKDIR /app

COPY HW3/mcp/requirements.txt ./requirements.txt
# Zámek s hashi z requirements.in (příkaz v hlavičce souboru). Balíček bez
# shody hashe nebo mimo zámek pip odmítne, viz security/04-mitigace.md (M8).
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt

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
