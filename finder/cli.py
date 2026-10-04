import argparse
import sys

from dotenv import load_dotenv

from . import db
from .sources.osm import CATEGORIES, OsmSource, resolve_areas


def cmd_scan(args: argparse.Namespace) -> int:
    areas = resolve_areas(args.area, args.hint)
    if not areas:
        print(f"No place found for '{args.area}'" + (f" with hint '{args.hint}'" if args.hint else ""))
        return 1

    print(f"Candidates for '{args.area}':")
    for i, a in enumerate(areas, 1):
        kind = "boundary" if a.has_boundary else "point"
        print(f"  [{i}] ({a.osm_type}, {a.place_type}, {kind}) {a.display_name}")

    if len(areas) > 1 and args.pick is None:
        print("\nMore than one match. Re-run with --pick N (or narrow with --hint TEXT).")
        return 2

    area = areas[(args.pick or 1) - 1]
    how = "inside its boundary" if area.has_boundary else f"within {args.radius} m of its center point"
    print(f"\nUsing [{args.pick or 1}]: {area.display_name}\nSearching '{args.category}' {how}...\n")

    businesses = OsmSource(radius=args.radius).search(area, args.category)
    for b in sorted(businesses, key=lambda b: b.name):
        site = b.website_url or "-"
        print(f"{b.name} | {b.phone or '-'} | {b.address or '-'} | site: {site}")

    no_site = sum(1 for b in businesses if not b.website_url)
    print(f"\n{len(businesses)} businesses, {no_site} without a website in OSM.")
    if not args.no_save:
        with db.connect() as conn:
            c = db.save_scan(conn, area.name, args.category, "osm", businesses)
        print(f"Saved: {c['new']} new, {c['updated']} updated, {c['unchanged']} unchanged.")
    print("Data © OpenStreetMap contributors")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        rows = db.list_businesses(conn, args.area, args.category, args.status)
    for r in rows:
        print(f"[{r['site_status']}] {r['name']} | {r['phone'] or '-'} | {r['address'] or '-'} | "
              f"{r['area']}/{r['category']} | {r['contact_status']}")
    print(f"\n{len(rows)} businesses (do_not_call hidden).")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="finder")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="fetch businesses for an area and category")
    scan.add_argument("--area", required=True, help='place name, e.g. "Καλαμαριά"')
    scan.add_argument("--category", required=True, help=f"one of: {', '.join(sorted(CATEGORIES))}, or key=value")
    scan.add_argument("--hint", help='keep only places whose address contains this, e.g. "Θεσσαλονίκη"')
    scan.add_argument("--pick", type=int, help="choose candidate N when several match")
    scan.add_argument("--radius", type=int, default=1500, help="meters, for places that are only a point")
    scan.add_argument("--no-save", action="store_true", help="print only, do not write to the database")
    scan.set_defaults(func=cmd_scan)

    ls = sub.add_parser("list", help="show saved businesses")
    ls.add_argument("--area")
    ls.add_argument("--category")
    ls.add_argument("--status", choices=["unchecked", "none", "dead", "social_only", "alive"])
    ls.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
