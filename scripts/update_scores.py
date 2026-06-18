#!/usr/bin/env python3
"""
Pulls completed 2026 FIFA World Cup group-stage scores from ESPN's public
(unofficial) scoreboard API and writes them to data/results.json in the
same shape the site's index.html expects.

No API key needed. Safe to run as often as you like (daily by default via
the GitHub Action in .github/workflows/update-scores.yml).
"""
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Mirrors the GROUPS fixture list in index.html. Order matters: each
# match's index here must match its index in that group's "matches" array
# in index.html, since results.json is keyed by "<group>_<index>".
FIXTURES = {
    "A": [("Mexico", "South Africa"), ("South Korea", "Czechia"),
          ("Czechia", "South Africa"), ("Mexico", "South Korea"),
          ("Czechia", "Mexico"), ("South Africa", "South Korea")],
    "B": [("Canada", "Bosnia and Herzegovina"), ("Qatar", "Switzerland"),
          ("Switzerland", "Bosnia and Herzegovina"), ("Canada", "Qatar"),
          ("Switzerland", "Canada"), ("Bosnia and Herzegovina", "Qatar")],
    "C": [("Brazil", "Morocco"), ("Haiti", "Scotland"),
          ("Scotland", "Morocco"), ("Brazil", "Haiti"),
          ("Scotland", "Brazil"), ("Morocco", "Haiti")],
    "D": [("United States", "Paraguay"), ("Australia", "Türkiye"),
          ("United States", "Australia"), ("Türkiye", "Paraguay"),
          ("Türkiye", "United States"), ("Paraguay", "Australia")],
    "E": [("Germany", "Curaçao"), ("Ivory Coast", "Ecuador"),
          ("Germany", "Ivory Coast"), ("Ecuador", "Curaçao"),
          ("Ecuador", "Germany"), ("Curaçao", "Ivory Coast")],
    "F": [("Netherlands", "Japan"), ("Sweden", "Tunisia"),
          ("Netherlands", "Sweden"), ("Tunisia", "Japan"),
          ("Japan", "Sweden"), ("Tunisia", "Netherlands")],
    "G": [("Belgium", "Egypt"), ("Iran", "New Zealand"),
          ("Belgium", "Iran"), ("New Zealand", "Egypt"),
          ("Egypt", "Iran"), ("New Zealand", "Belgium")],
    "H": [("Spain", "Cape Verde"), ("Saudi Arabia", "Uruguay"),
          ("Spain", "Saudi Arabia"), ("Uruguay", "Cape Verde"),
          ("Cape Verde", "Saudi Arabia"), ("Uruguay", "Spain")],
    "I": [("France", "Senegal"), ("Iraq", "Norway"),
          ("France", "Iraq"), ("Norway", "Senegal"),
          ("Norway", "France"), ("Senegal", "Iraq")],
    "J": [("Argentina", "Algeria"), ("Austria", "Jordan"),
          ("Argentina", "Austria"), ("Jordan", "Algeria"),
          ("Algeria", "Austria"), ("Jordan", "Argentina")],
    "K": [("Portugal", "DR Congo"), ("Uzbekistan", "Colombia"),
          ("Portugal", "Uzbekistan"), ("Colombia", "DR Congo"),
          ("Colombia", "Portugal"), ("DR Congo", "Uzbekistan")],
    "L": [("England", "Croatia"), ("Ghana", "Panama"),
          ("England", "Ghana"), ("Panama", "Croatia"),
          ("Panama", "England"), ("Croatia", "Ghana")],
}

# ESPN sometimes uses a different display name than the one used above —
# add to this if a match doesn't get picked up.
NAME_ALIASES = {
    "Czechia": ["Czechia", "Czech Republic"],
    "Ivory Coast": ["Ivory Coast", "Côte d'Ivoire", "Cote d'Ivoire"],
    "Cape Verde": ["Cape Verde", "Cabo Verde"],
    "Türkiye": ["Türkiye", "Turkey"],
    "DR Congo": ["DR Congo", "Congo DR", "DRC"],
    "Curaçao": ["Curaçao", "Curacao"],
    "Bosnia and Herzegovina": ["Bosnia and Herzegovina", "Bosnia & Herzegovina", "Bosnia-Herzegovina"],
    "United States": ["United States", "USA"],
}

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?limit=200&dates=20260611-20260719"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "results.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def aliases(name: str):
    return NAME_ALIASES.get(name, [name])


def fetch_events():
    req = urllib.request.Request(ESPN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8")).get("events", [])


def index_by_pair(events):
    by_pair = {}
    for ev in events:
        comp = ev["competitions"][0]
        names, scores = {}, {}
        for c in comp["competitors"]:
            names[c["homeAway"]] = c["team"]["displayName"]
            scores[c["homeAway"]] = c.get("score")
        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        key = frozenset([norm(names.get("home", "")), norm(names.get("away", ""))])
        by_pair[key] = {"names": names, "scores": scores, "completed": completed, "odds": comp.get("odds", [])}
    return by_pair


def predict_score(odds_list):
    """Very rough 'expected scoreline' from a spread + total line. Not a real
    forecast — just spread/2 +/- total/2, rounded. Returns (home_goals,
    away_goals) in ESPN's home/away frame, or None if no usable odds."""
    if not odds_list:
        return None
    odds = odds_list[0]
    total_line = odds.get("overUnder")
    spread = odds.get("pointSpread", {}).get("home", {})
    spread_line = (spread.get("close") or spread.get("open") or {}).get("line")
    if total_line is None or spread_line is None:
        return None
    try:
        total_line = float(total_line)
        home_adv = -float(spread_line)  # negative spread = home favored
    except (TypeError, ValueError):
        return None
    home_expected = total_line / 2 + home_adv / 2
    away_expected = total_line / 2 - home_adv / 2
    return (max(0, round(home_expected)), max(0, round(away_expected)))


def main():
    events = fetch_events()
    by_pair = index_by_pair(events)

    results = {}
    predictions = {}
    for g, matches in FIXTURES.items():
        for idx, (h, a) in enumerate(matches):
            found = None
            for hn in aliases(h):
                for an in aliases(a):
                    key = frozenset([norm(hn), norm(an)])
                    if key in by_pair:
                        found = by_pair[key]
                        break
                if found:
                    break
            if not found:
                continue
            home_is_h = norm(found["names"].get("home", "")) in [norm(x) for x in aliases(h)]

            if found["completed"]:
                hs, as_ = (found["scores"]["home"], found["scores"]["away"]) if home_is_h \
                    else (found["scores"]["away"], found["scores"]["home"])
                try:
                    results[f"{g}_{idx}"] = {"hs": int(hs), "as": int(as_)}
                except (TypeError, ValueError):
                    continue
            else:
                pred = predict_score(found.get("odds", []))
                if pred is None:
                    continue
                home_g, away_g = pred
                hs, as_ = (home_g, away_g) if home_is_h else (away_g, home_g)
                predictions[f"{g}_{idx}"] = {"hs": int(hs), "as": int(as_)}

    out = {
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "predictions": predictions,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} completed results and {len(predictions)} odds-based predictions to {OUT_PATH}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Pulls completed 2026 FIFA World Cup group-stage scores from ESPN's public
(unofficial) scoreboard API and writes them to data/results.json in the
same shape the site's index.html expects.

No API key needed. Safe to run as often as you like (daily by default via
the GitHub Action in .github/workflows/update-scores.yml).
"""
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Mirrors the GROUPS fixture list in index.html. Order matters: each
# match's index here must match its index in that group's "matches" array
# in index.html, since results.json is keyed by "<group>_<index>".
FIXTURES = {
    "A": [("Mexico", "South Africa"), ("South Korea", "Czechia"),
          ("Czechia", "South Africa"), ("Mexico", "South Korea"),
          ("Czechia", "Mexico"), ("South Africa", "South Korea")],
    "B": [("Canada", "Bosnia and Herzegovina"), ("Qatar", "Switzerland"),
          ("Switzerland", "Bosnia and Herzegovina"), ("Canada", "Qatar"),
          ("Switzerland", "Canada"), ("Bosnia and Herzegovina", "Qatar")],
    "C": [("Brazil", "Morocco"), ("Haiti", "Scotland"),
          ("Scotland", "Morocco"), ("Brazil", "Haiti"),
          ("Scotland", "Brazil"), ("Morocco", "Haiti")],
    "D": [("United States", "Paraguay"), ("Australia", "Türkiye"),
          ("United States", "Australia"), ("Türkiye", "Paraguay"),
          ("Türkiye", "United States"), ("Paraguay", "Australia")],
    "E": [("Germany", "Curaçao"), ("Ivory Coast", "Ecuador"),
          ("Germany", "Ivory Coast"), ("Ecuador", "Curaçao"),
          ("Ecuador", "Germany"), ("Curaçao", "Ivory Coast")],
    "F": [("Netherlands", "Japan"), ("Sweden", "Tunisia"),
          ("Netherlands", "Sweden"), ("Tunisia", "Japan"),
          ("Japan", "Sweden"), ("Tunisia", "Netherlands")],
    "G": [("Belgium", "Egypt"), ("Iran", "New Zealand"),
          ("Belgium", "Iran"), ("New Zealand", "Egypt"),
          ("Egypt", "Iran"), ("New Zealand", "Belgium")],
    "H": [("Spain", "Cape Verde"), ("Saudi Arabia", "Uruguay"),
          ("Spain", "Saudi Arabia"), ("Uruguay", "Cape Verde"),
          ("Cape Verde", "Saudi Arabia"), ("Uruguay", "Spain")],
    "I": [("France", "Senegal"), ("Iraq", "Norway"),
          ("France", "Iraq"), ("Norway", "Senegal"),
          ("Norway", "France"), ("Senegal", "Iraq")],
    "J": [("Argentina", "Algeria"), ("Austria", "Jordan"),
          ("Argentina", "Austria"), ("Jordan", "Algeria"),
          ("Algeria", "Austria"), ("Jordan", "Argentina")],
    "K": [("Portugal", "DR Congo"), ("Uzbekistan", "Colombia"),
          ("Portugal", "Uzbekistan"), ("Colombia", "DR Congo"),
          ("Colombia", "Portugal"), ("DR Congo", "Uzbekistan")],
    "L": [("England", "Croatia"), ("Ghana", "Panama"),
          ("England", "Ghana"), ("Panama", "Croatia"),
          ("Panama", "England"), ("Croatia", "Ghana")],
}

# ESPN sometimes uses a different display name than the one used above —
# add to this if a match doesn't get picked up.
NAME_ALIASES = {
    "Czechia": ["Czechia", "Czech Republic"],
    "Ivory Coast": ["Ivory Coast", "Côte d'Ivoire", "Cote d'Ivoire"],
    "Cape Verde": ["Cape Verde", "Cabo Verde"],
    "Türkiye": ["Türkiye", "Turkey"],
    "DR Congo": ["DR Congo", "Congo DR", "DRC"],
    "Curaçao": ["Curaçao", "Curacao"],
    "Bosnia and Herzegovina": ["Bosnia and Herzegovina", "Bosnia & Herzegovina", "Bosnia-Herzegovina"],
    "United States": ["United States", "USA"],
}

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?limit=200&dates=20260611-20260719"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "results.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def aliases(name: str):
    return NAME_ALIASES.get(name, [name])


def fetch_events():
    req = urllib.request.Request(ESPN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8")).get("events", [])


def index_by_pair(events):
    by_pair = {}
    for ev in events:
        comp = ev["competitions"][0]
        names, scores = {}, {}
        for c in comp["competitors"]:
            names[c["homeAway"]] = c["team"]["displayName"]
            scores[c["homeAway"]] = c.get("score")
        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        key = frozenset([norm(names.get("home", "")), norm(names.get("away", ""))])
        by_pair[key] = {"names": names, "scores": scores, "completed": completed}
    return by_pair


def main():
    events = fetch_events()
    by_pair = index_by_pair(events)

    results = {}
    for g, matches in FIXTURES.items():
        for idx, (h, a) in enumerate(matches):
            found = None
            for hn in aliases(h):
                for an in aliases(a):
                    key = frozenset([norm(hn), norm(an)])
                    if key in by_pair:
                        found = by_pair[key]
                        break
                if found:
                    break
            if not found or not found["completed"]:
                continue
            home_is_h = norm(found["names"].get("home", "")) in [norm(x) for x in aliases(h)]
            hs, as_ = (found["scores"]["home"], found["scores"]["away"]) if home_is_h \
                else (found["scores"]["away"], found["scores"]["home"])
            try:
                results[f"{g}_{idx}"] = {"hs": int(hs), "as": int(as_)}
            except (TypeError, ValueError):
                continue

    out = {
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} completed match results to {OUT_PATH}")


if __name__ == "__main__":
    main()
