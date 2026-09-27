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

Weitere Reiter: **Branchen** (Branchenpaket, eigene Quellen), **Aufträge**, **Bibliothek** (inkl. Beobachtungsliste), **Universum** (Katalog aller EU-Aktien und Stapelabruf), **Einstellungen**.

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
```

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
