HW2: agent nad výkazy v n8n a LangFlow

Nástroje z HW1 vystavené jako HTTP API (`HW2/api`), nad ním týž agent ve dvou
no-code platformách. Obojí 8/8 na osmi dotazech; měření spouští
`scripts/compare_platforms.py` a očekávané hodnoty si počítá z API, takže
nezestárne s přegenerováním datasetu.

Telegram bot jede pollingem, ne webhookem. Workflow se generují skriptem
ze schémat z `GET /tools`, ne klikáním. Hlavní výstup je docs/srovnani.md.

