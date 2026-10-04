"""Build wishlist.txt from rolls.toml using names, resolved against Bungie's live manifest."""
import difflib, json, re, sys, tomllib, urllib.request
from itertools import product
from pathlib import Path

BNET = "https://www.bungie.net"
CACHE = Path(".cache")
WEAPON_PERKS = 4241085061  # socket category: barrel, mag, trait 1, trait 2, (origin...)


def table(name, paths, version):
    f = CACHE / f"{version}-{name}.json"
    if not f.exists():
        CACHE.mkdir(exist_ok=True)
        for old in CACHE.glob(f"*-{name}.json"):
            old.unlink()
        print(f"downloading {name}...", file=sys.stderr)
        urllib.request.urlretrieve(BNET + paths[name], f)
    return json.loads(f.read_text())


def load():
    m = json.load(urllib.request.urlopen(f"{BNET}/Platform/Destiny2/Manifest/"))["Response"]
    paths = m["jsonWorldComponentContentPaths"]["en"]
    return (table("DestinyInventoryItemDefinition", paths, m["version"]),
            table("DestinyPlugSetDefinition", paths, m["version"]))


def columns(item, items, plugsets):
    """[{perk name: base perk hash}] for the 4 random perk columns of a weapon."""
    sockets = item["sockets"]
    idx = next(c["socketIndexes"] for c in sockets["socketCategories"] if c["socketCategoryHash"] == WEAPON_PERKS)
    cols = []
    for i in idx:
        e = sockets["socketEntries"][i]
        ps = e.get("randomizedPlugSetHash") or e.get("reusablePlugSetHash")
        if not ps:
            continue
        pool = {}
        for p in plugsets[str(ps)]["reusablePlugItems"]:
            d = items[str(p["plugItemHash"])]
            # tierType 3 = enhanced; DIM matches enhanced perks against the base hash
            if d.get("inventory", {}).get("tierType") != 3:
                pool.setdefault(d["displayProperties"]["name"].lower(), p["plugItemHash"])
        cols.append(pool)
    return cols[:4]


def trait_sets(item):
    """The randomized plug sets of the weapon-perk sockets; equal sets = same perk pool."""
    sockets = item["sockets"]
    idx = next(c["socketIndexes"] for c in sockets["socketCategories"] if c["socketCategoryHash"] == WEAPON_PERKS)
    return tuple(sockets["socketEntries"][i].get("randomizedPlugSetHash") for i in idx)


def current_versions(versions):
    """Only the newest release (manifest index ~ release order) plus versions sharing its perk pool, e.g. its Adept."""
    newest = max(versions, key=lambda i: i["index"])
    return [i for i in versions if trait_sets(i) == trait_sets(newest)]


def main():
    cfg = tomllib.loads(Path("rolls.toml").read_text())
    items, plugsets = load()
    by_name = {}
    for i in items.values():
        if i.get("itemType") == 3 and "sockets" in i and any(
                e.get("randomizedPlugSetHash") for e in i["sockets"]["socketEntries"]):
            # "Igneous Hammer (Adept)" / "(Timelost)" / "(Harrowed)" count as the same weapon
            base = re.sub(r"\s*\((adept|timelost|harrowed)\)$", "", i["displayProperties"]["name"].lower())
            by_name.setdefault(base, []).append(i)

    out = [f"title:{cfg['title']}", f"description:{cfg['description']}", ""]
    errors = []
    for roll in cfg.get("roll", []):
        name = roll["weapon"]
        versions = by_name.get(name.lower())
        if not versions:
            errors.append(f"{name}: unknown weapon (did you mean {difflib.get_close_matches(name.lower(), by_name, 3)}?)")
            continue
        versions = current_versions(versions)
        out.append(f"//notes:{roll.get('notes', name)}")
        found, options = set(), [set() for _ in roll["perks"]]
        for item in versions:  # reissues/adepts share a name; wishlist them all
            cols = columns(item, items, plugsets)
            picks = []
            for c, (want, pool) in enumerate(zip(roll["perks"], cols)):
                options[c] |= pool.keys()
                hashes = [pool[w.lower()] for w in want if w.lower() in pool]
                found |= {(c, w.lower()) for w in want if w.lower() in pool}
                picks.append(hashes)
            if any(want and not got for want, got in zip(roll["perks"], picks)):
                continue  # this version can't roll the requested perks
            # an empty column means "any"
            for combo in product(*[p for p in picks if p]):
                perks = f"&perks={','.join(map(str, combo))}" if combo else ""
                sign = "-" if roll.get("trash") else ""  # negative hash = thumbs down in DIM
                out.append(f"dimwishlist:item={sign}{item['hash']}{perks}")
        out.append("")
        for c, want in enumerate(roll["perks"]):
            for w in want:
                if (c, w.lower()) not in found:
                    errors.append(f"{name}: '{w}' can't roll in column {c + 1} (options: {sorted(options[c])})")

    if errors:
        sys.exit("\n".join(errors))
    Path("wishlist.txt").write_text("\n".join(out))
    print(f"wrote {sum(l.startswith('dimwishlist') for l in out)} lines", file=sys.stderr)


if __name__ == "__main__":
    main()
