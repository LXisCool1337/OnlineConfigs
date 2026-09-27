"""Command line: python -m portal <command>. Run ``python -m portal --help`` for the list."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser

from .app import App
from .config import load_settings
from . import financials, fulltext
from .pipeline import CATEGORY_LABELS
from .resolver import Resolver

COLORS = {"ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m", "stage": "\033[1m", "summary": "\033[1m",
          "hint": "\033[36m"}


def echo(level: str, message: str, data: dict) -> None:
    color = COLORS.get(level, "") if sys.stdout.isatty() else ""
    reset = "\033[0m" if color else ""
    prefix = {"stage": "==>", "ok": " + ", "warn": " ! ", "error": " x ", "summary": " = ", "hint": " ? "}.get(level, "   ")
    print(f"{color}{prefix} {message}{reset}", flush=True)


def _de(value: float, decimals: int) -> str:
    """German number format: 5.663,8"""
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _include(args) -> dict:
    return {"esef": not args.no_esef, "pdf": not args.no_pdf, "websearch": not args.no_websearch,
            "sustainability": args.sustainability, "industry": args.industry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m portal", description="EU-Report-Portal")
    parser.add_argument("--config", help="Pfad zu portal.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="Weboberfläche starten")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--open", action="store_true", help="Browser öffnen")

    p = sub.add_parser("search", help="Unternehmen suchen (Name, ISIN, LEI)")
    p.add_argument("query")

    p = sub.add_parser("fetch", help="Geschäftsberichte eines Unternehmens laden")
    p.add_argument("query", help="Name, ISIN oder LEI")
    p.add_argument("--years", type=int)
    p.add_argument("--ir-url", help="IR-Seite oder Berichtsarchiv")
    p.add_argument("--website")
    p.add_argument("--lang", help="Sprachreihenfolge, z. B. en,local")
    p.add_argument("--all-languages", action="store_true")
    p.add_argument("--url", action="append", default=[], help="zusätzlicher PDF-Link, optional '2017: URL'")
    p.add_argument("--industry", action="store_true", help="Branchenpaket mitladen")
    p.add_argument("--nace", help="NACE-Code, z. B. 28 oder 28.29")
    p.add_argument("--keywords")
    p.add_argument("--peers", help="Wettbewerber, kommagetrennt")
    p.add_argument("--sustainability", action="store_true")
    p.add_argument("--no-esef", action="store_true")
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--no-websearch", action="store_true")

    p = sub.add_parser("industry", help="Branchenpaket laden")
    p.add_argument("nace")
    p.add_argument("--company", help="Bezugsunternehmen (Name, ISIN, LEI) für Wettbewerber und Vergleich")
    p.add_argument("--keywords")
    p.add_argument("--country")
    p.add_argument("--peers")
    p.add_argument("--years", type=int)

    p = sub.add_parser("universe", help="Katalog aller EU-Aktien aktualisieren")
    p.add_argument("--source", choices=["esef", "firds"], default="esef")

    p = sub.add_parser("batch", help="Stapelabruf für viele Unternehmen (läuft im Vordergrund)")
    p.add_argument("--country", help="Länder, kommagetrennt (z. B. DE,AT)")
    p.add_argument("--esef-only", action="store_true")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--years", type=int)
    p.add_argument("--industry", action="store_true")

    sub.add_parser("refresh", help="Beobachtungsliste aktualisieren (für cron)")

    p = sub.add_parser("export", help="Unternehmensordner als ZIP exportieren")
    p.add_argument("lei")

    p = sub.add_parser("figures", help="Kennzahlen aus den ESEF-Berichten anzeigen (neu berechnen)")
    p.add_argument("query", help="Name, ISIN oder LEI")
    p.add_argument("--csv", choices=["de", "en"], help="als CSV ausgeben")

    sub.add_parser("index", help="Volltext indizieren und Kennzahlen neu berechnen")

    p = sub.add_parser("grep", help="Volltextsuche in allen Berichten")
    p.add_argument("query", help='Suchbegriffe, "Phrase", Wortanfang*')
    p.add_argument("--lei")
    p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    app = App(settings, echo=echo)

    if args.command == "serve":
        from .server import serve
        server = serve(app, args.host, args.port)
        app.jobs.start(scheduler=True)
        host, port = server.server_address[:2]
        url = f"http://{'localhost' if host in ('127.0.0.1', '::1') else host}:{port}/"
        print(f"EU-Report-Portal läuft auf {url}  (Bibliothek: {settings.library_dir})", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.close()
        return 0

    if args.command == "search":
        results, warning = Resolver(app.context(echo=echo)).search(args.query)
        if warning:
            print(warning)
        for c in results:
            flags = " ".join(f for f, on in (("börsennotiert", c.get("listed")), ("ESEF", c.get("has_esef"))) if on)
            print(f"{c['lei']}  {c.get('country') or '??'}  {c['name']}  {flags}")
        return 0

    if args.command == "export":
        company = app.db.company(args.lei)
        if not company:
            print("Unbekannte LEI")
            return 1
        path = app.library.build_zip(app.library.company_dir(company), f"{company['name']}_{company['lei']}")
        print(path)
        return 0

    if args.command == "figures":
        company = Resolver(app.context(echo=echo)).resolve(query=args.query)
        financials.extract(app.context(echo=echo), company["lei"])
        if args.csv:
            sys.stdout.write(financials.csv_for(app.db, company["lei"], args.csv))
            return 0
        data = financials.table_for(app.db, company["lei"])
        if not data["years"]:
            print("Keine ESEF-Berichte in der Bibliothek. Zuerst: python -m portal fetch", args.query)
            return 1
        print(f"{company['name']} · {data['currency']} · Beträge in Mio.")
        print(f"{'':28}" + "".join(f"{y:>11}" for y in data["years"]))
        for m in data["metrics"]:
            cells = []
            for y in data["years"]:
                v = m["values"].get(str(y))
                if v is None:
                    cells.append(f"{'–':>11}")
                elif m["unit"] == "pct":
                    cells.append(f"{_de(v * 100, 1) + ' %':>11}")
                elif m["unit"] == "per_share":
                    cells.append(f"{_de(v, 2):>11}")
                else:
                    cells.append(f"{_de(v / 1e6, 1):>11}")
            print(f"{m['label'][:27]:28}" + "".join(cells))
        return 0

    if args.command == "grep":
        hits = fulltext.search(app.db, args.query, lei=args.lei, limit=args.limit)
        for hit in hits:
            company = (app.db.company(hit["lei"]) or {}).get("name") or hit["nace"] or ""
            where = f"S. {hit['page']}" if hit["page"] else ""
            snippet = hit["snippet"].replace(fulltext.MARK_START, "»").replace(fulltext.MARK_END, "«")
            print(f"{company} · {hit['fy_label'] or hit['fiscal_year'] or ''} · {hit['title']} {where}\n    {snippet}\n")
        if not hits:
            print("Keine Treffer.")
        return 0

    if args.command == "fetch":
        params = {"query": args.query, "include": _include(args), "urls": args.url, "all_languages": args.all_languages}
        for key in ("years", "ir_url", "website", "nace", "keywords", "peers"):
            if getattr(args, key, None):
                params[key] = getattr(args, key)
        if args.lang:
            params["languages"] = [x.strip() for x in args.lang.split(",") if x.strip()]
        job = app.jobs.run_sync("company", params)
    elif args.command == "industry":
        params = {k: getattr(args, k) for k in ("nace", "keywords", "country", "peers", "years") if getattr(args, k)}
        if args.company:
            company = Resolver(app.context(echo=echo)).resolve(query=args.company)
            params["company_lei"] = company["lei"]
            params.setdefault("country", company.get("country"))
        job = app.jobs.run_sync("industry", params)
    elif args.command == "universe":
        job = app.jobs.run_sync("universe", {"source": args.source})
    elif args.command == "index":
        job = app.jobs.run_sync("index", {})
    elif args.command in ("batch", "refresh"):
        params = {"countries": args.country or "", "esef_only": args.esef_only, "limit": args.limit,
                  "include": {"industry": args.industry}} if args.command == "batch" else {}
        if args.command == "batch" and args.years:
            params["years"] = args.years
        job = app.jobs.run_sync(args.command, params)
        while True:  # work through the queued company jobs in this process
            nxt = app.db.claim_job()
            if nxt is None:
                break
            print(f"\n### Auftrag #{nxt['id']}: {nxt['title']}")
            app.jobs.run(nxt)
    else:
        parser.error("unbekannter Befehl")
        return 2

    print(json.dumps({"status": job["status"], **(job.get("summary") or {})}, ensure_ascii=False, indent=2,
                     default=str))
    if job["status"] == "done" and args.command == "fetch":
        company = app.db.company(job["summary"]["lei"])
        folder = app.library.company_dir(company)
        print(f"\nDokumente in: {folder}")
        for doc in app.db.company_documents(company["lei"]):
            print(f"  {doc['fy_label'] or doc['fiscal_year'] or '----':8} {CATEGORY_LABELS.get(doc['category'], doc['category']):28}"
                  f" {doc['language'] or '':3} {doc['path']}")
    app.db.close()
    return 0 if job["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
