HW3: nástroje z HW1 jako MCP server, tři agenti nad ním

MCP server (Python, low-level Server) obaluje `timeagent.tools` bez doménové
logiky — schémata se přebírají z TOOL_SCHEMAS doslova, aby se nezahodily popisy
laděné pro model. Dvě záruky z HW1 drží i přes protokol a hlídají je testy:
chyba jde jako data (is_error se nenastavuje ani pro {"error": ...}) a pole
`note` u prázdného výsledku dojde ke klientovi.

Agenti: Microsoft Agent Framework (.NET), LangGraph a Pydantic AI. Stejný
prompt pro všechny — generuje ho `scripts/export_system_prompt.py` z HW1.
Naměřeno 8/8, 8/8 a 7/8; LangGraph po chybě nástroje neudělal druhé kolo
a hlášku opsal do odpovědi.

Na týž server se připojily i n8n a LangFlow z HW2. HW2 stack se nemění —
LangFlow potřebuje jen compose překryv kvůli SSRF allowlistu.

Navíc druhý MCP server v C# jako proxy nad API z HW2, cvičení na serverovou
stranu SDK; schémata i výsledky má bit-identické s Python serverem.

