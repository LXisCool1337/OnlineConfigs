# EU-Report-Portal

Lädt für jedes börsennotierte Unternehmen in EU und EWR die **Geschäftsberichte der letzten 10 Jahre** und stellt ein **Branchenpaket** zusammen: Eurostat-Statistik, Open-Access-Studien, Verbandsberichte und die Berichte der Wettbewerber. Wie und warum es so funktioniert, steht im Plan: [`docs/PLAN.md`](../docs/PLAN.md).

Das Portal nutzt nur die Python-Standardbibliothek (ab 3.11). Es gibt nichts zu installieren.

## Start

```bash
python3 -m portal serve --open
```

Das öffnet http://localhost:8765. Beim ersten Start unter **Einstellungen** eine Kontakt-E-Mail eintragen: Sie wird im User-Agent an die Datenquellen gesendet, und Wikidata und OpenAlex erwarten das.

1. **Unternehmen** suchen: Name, ISIN (z. B. `DE0006335003`) oder LEI.
2. Optional die IR-Seite bzw. das Berichtsarchiv und die Branche (NACE) eintragen.
3. **Berichte laden**. Das Live-Protokoll zeigt jeden Schritt; danach folgen die Abdeckungsmatrix (Jahr × PDF/ESEF), die Dokumentliste und der ZIP-Export.

Die Reiter:

| Reiter | Inhalt |
|---|---|
| **Übersicht** | Bestand, Speicher, zuletzt geladene Dokumente, Unternehmen mit Lücken, laufende Aufträge, Beobachtungsliste |
| **Unternehmen** | Abruf, Abdeckung (fehlende Jahre per Klick ergänzen), **Kennzahlen aus den ESEF-Berichten** mit Diagrammen und Excel-Export, Dokumentliste („Falsch“ ersetzt ein Dokument beim nächsten Lauf durch die nächstbeste Quelle) |
| **Branchen** | Branchenpaket, eigene Quellen, **Wettbewerbervergleich** (Margen, Wachstum, Eigenkapitalquote, ROE, Median) |
| **Volltext** | Suche in allen Berichten: Wörter, „Phrasen“, Wortanfang* (Zoll* findet Zölle, Zollpolitik), Filter nach Unternehmen und Jahren |
| **Aufträge**, **Bibliothek**, **Universum** | Auftragsprotokolle, Bestand, Katalog aller EU-Aktien und Stapelabruf |
| **Einstellungen** | Kontakt-E-Mail, Sprachen, Websuche und automatische Aktualisierung der Beobachtungsliste (alle N Tage) |

## Kommandozeile

```bash
python3 -m portal search "Krones"
python3 -m portal fetch DE0006335003 --industry --nace 28 --keywords "Abfüllanlagen, Verpackungsmaschinen"
python3 -m portal fetch DE0006335003 --ir-url "https://…/investor-relations/berichte" --url "2016: https://…/gb-2016.pdf"
python3 -m portal industry 28 --country DE --peers "GEA Group"
python3 -m portal universe --source esef       # schnell: alle ESEF-Emittenten
python3 -m portal universe --source firds      # vollständig: ESMA-Referenzdaten
python3 -m portal batch --country DE,AT --esef-only --limit 50
python3 -m portal refresh                      # Beobachtungsliste aktualisieren (cron)
python3 -m portal export <LEI>
python3 -m portal figures DE0006335003         # Kennzahlen-Tabelle (--csv de: Excel-CSV)
python3 -m portal grep "Zoll*" --limit 10      # Volltextsuche über alle Berichte
python3 -m portal index                        # Volltext nachindizieren, Kennzahlen neu berechnen
```

## Kennzahlen und Volltext

Die Kennzahlen stammen direkt aus dem Inline-XBRL der ESEF-Berichte: Umsatz, EBIT, Jahresergebnis, Ergebnis je Aktie, Cashflow, Investitionen, Bilanz und daraus Margen, Free Cashflow, Eigenkapitalquote und ROE. Jeder Bericht enthält auch das Vorjahr, daher ergeben sechs Berichte sieben Jahre. Angezeigt werden die ursprünglich berichteten Werte; spätere Anpassungen erscheinen als Hinweis.

Die Volltextsuche deckt die ESEF-Berichte immer ab. PDFs werden durchsuchbar, sobald `pdftotext` installiert ist (Linux: `apt install poppler-utils`, macOS: `brew install poppler`, Windows: Poppler-Binaries in den PATH). Danach einmal `python3 -m portal index` ausführen.

## Wo die Dateien landen

```
library/companies/<Land>/<name>_<LEI>/<Jahr>/annual_report_2019_en.pdf
                                            /esef_report_2021.xhtml, esef_package_2021.zip
                                     manifest.json   (Quelle, SHA-256, Abrufzeit je Datei)
library/industries/nace-28/{statistics,studies,associations,peers,web}/…
library/exports/*.zip
library/portal.sqlite3
```

## Konfiguration

Kopiere [`portal.example.toml`](../portal.example.toml) nach `portal.toml`, oder setze Umgebungsvariablen `PORTAL_<NAME>` (z. B. `PORTAL_CONTACT_EMAIL`). Die wichtigsten Werte lassen sich auch in der Oberfläche ändern. Die Websuche (Brave Search API oder eigenes SearXNG) ist optional und schließt Lücken bei älteren PDFs.

Soll das Portal auf einer anderen Adresse als `127.0.0.1` laufen, muss `access_token` gesetzt sein. Der Aufruf erfolgt dann mit `?token=…`.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Die Tests laufen komplett offline gegen ein nachgebautes Internet ([`tests/fakeweb.py`](../tests/fakeweb.py)).

## Grenzen

- ESEF-Berichte gibt es ab Geschäftsjahr 2020. Ältere Jahre kommen aus dem IR-Archiv des Unternehmens, aus der Websuche oder aus manuellen Links.
- IR-Seiten, die ihre Berichtslisten nur per JavaScript aufbauen, sieht der Crawler nicht. Dann hilft die IR-URL der Archivseite, die Websuche oder ein manueller Link.
- Kommerzielle Branchenstudien hinter Bezahlschranken werden nicht geladen. robots.txt, Logins und Captchas werden respektiert.
- Nur für die eigene Recherche. Keine Anlageberatung.
