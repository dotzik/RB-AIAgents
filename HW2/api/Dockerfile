# Build context je kořen repozitáře (RB-AIAgents/), ne tenhle adresář —
# image potřebuje sáhnout do HW1/ pro balíček s nástroji.
#   docker build -f HW2/api/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY HW2/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Nástroje se nekopírují ani nepřepisují — instaluje se balíček z HW1.
#
# `--no-deps` je záměr, ne úspora místa. HW1 deklaruje litellm a python-dotenv,
# ale `tools.py` ani `db.py` z LLM světa nic neimportují (viz HW1/docs/architektura.md).
# Když se to jednou poruší, image spadne při startu na ImportError — tenhle řádek
# je tedy spustitelný test tvrzení o směru závislostí, ne jen optimalizace.
COPY HW1/pyproject.toml HW1/README.md ./hw1/
COPY HW1/src ./hw1/src
RUN pip install --no-cache-dir --no-deps ./hw1

COPY HW2/api/main.py ./main.py

# Databáze se mountuje read-only jako jediný soubor; cestu drží compose.
ENV TIMEAGENT_DB=/data/timeagent.sqlite

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
