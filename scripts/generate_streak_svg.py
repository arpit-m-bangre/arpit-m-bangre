#!/usr/bin/env python3
"""
Dynamic GitHub Streak & Contributions SVG Monitor
Reads live contribution calendars directly from GitHub, calculates exact
IST (Asia/Kolkata) unbroken streaks, generates crisp zero-dependency SVGs,
and can actively purge GitHub Camo proxy cache for real-time sync.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

USERNAME = os.environ.get("GH_USERNAME", "arpit-m-bangre")
START_YEAR = int(os.environ.get("GH_START_YEAR", "2024"))
IST_OFFSET = timedelta(hours=5, minutes=30)

THEMES = {
    "tokyonight": {
        "bg": "#1A1B27",
        "border": "#292E42",
        "accent_bar": "#00F2FE",
        "stroke": "#414868",
        "ring": "#BF91F3",
        "fire": "#F8D847",
        "curr_num": "#F8D847",
        "side_nums": "#70A5FD",
        "curr_label": "#BF91F3",
        "side_labels": "#A9B1D6",
        "dates": "#38BDF8",
        "footer_bg": "#141622",
        "footer_text": "#7AA2F7",
        "live_dot": "#10B981",
    },
    "radical": {
        "bg": "#141321",
        "border": "#2E2B4F",
        "accent_bar": "#FE428E",
        "stroke": "#A9FEF7",
        "ring": "#F8D847",
        "fire": "#FE428E",
        "curr_num": "#F8D847",
        "side_nums": "#FE428E",
        "curr_label": "#A9FEF7",
        "side_labels": "#A9FEF7",
        "dates": "#FE428E",
        "footer_bg": "#0F0E1A",
        "footer_text": "#A9FEF7",
        "live_dot": "#38BDF8",
    },
}


def fetch_calendar_html(username: str, year: int) -> tuple[dict[str, int], int]:
    """Fetch contribution HTML calendar for one calendar year from GitHub."""
    url = f"https://github.com/users/{username}/contributions?from={year}-01-01&to={year}-12-31"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GitHub-Streak-Monitor/1.0)",
            "Accept": "text/html",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    header_match = re.search(r"([\d,]+)\s+contributions?\s+in", html)
    year_total = int(header_match.group(1).replace(",", "")) if header_match else 0

    days: dict[str, int] = {}
    td_tags = re.findall(r"<td[^>]+contribution-day-component[^>]*>", html)
    tips = dict(
        re.findall(
            r'<tool-tip[^>]*for="(contribution-day-component-[^"]+)"[^>]*>([^<]+)</tool-tip>',
            html,
        )
    )

    for td in td_tags:
        id_m = re.search(r'id="([^"]+)"', td)
        dt_m = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', td)
        lv_m = re.search(r'data-level="(\d+)"', td)
        if not (id_m and dt_m and lv_m):
            continue
        cid = id_m.group(1)
        d_str = dt_m.group(1)
        lvl = int(lv_m.group(1))
        tip = tips.get(cid, "").strip()
        cnt_m = re.match(r"(\d+)\s+contribution", tip)
        if cnt_m:
            cnt = int(cnt_m.group(1))
        elif "No contributions" in tip:
            cnt = 0
        else:
            cnt = lvl
        days[d_str] = cnt

    return days, year_total


def fetch_calendar_graphql(username: str, year: int, token: str) -> tuple[dict[str, int], int]:
    """Fallback: fetch contribution calendar via GitHub GraphQL API."""
    query = """
    query($user: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $user) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    payload = json.dumps(
        {
            "query": query,
            "variables": {
                "user": username,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{year}-12-31T23:59:59Z",
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "GitHub-Streak-Monitor/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days: dict[str, int] = {}
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            days[day["date"]] = int(day["contributionCount"])
    return days, int(cal["totalContributions"])


def collect_contributions(username: str, start_year: int) -> dict:
    """Gather all daily contributions across all active years."""
    ist_now = datetime.now(timezone.utc) + IST_OFFSET
    ist_today = ist_now.date()
    utc_today = datetime.now(timezone.utc).date()
    end_year = max(ist_today.year, utc_today.year)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    all_days: dict[str, int] = {}
    header_total_sum = 0

    for year in range(start_year, end_year + 1):
        days: dict[str, int] = {}
        ytot = 0
        try:
            days, ytot = fetch_calendar_html(username, year)
        except Exception as exc:
            print(f"[WARN] HTML calendar fetch failed for {year}: {exc}", file=sys.stderr)

        if not days and token:
            try:
                days, ytot = fetch_calendar_graphql(username, year, token)
            except Exception as exc:
                print(f"[WARN] GraphQL calendar fetch failed for {year}: {exc}", file=sys.stderr)

        if not days:
            raise RuntimeError(f"Failed to retrieve contribution data for year {year}.")

        all_days.update(days)
        header_total_sum += ytot

    total_from_days = sum(all_days.values())
    total_contributions = max(header_total_sum, total_from_days)

    active_dates = sorted(d for d, cnt in all_days.items() if cnt > 0)
    first_active_date = active_dates[0] if active_dates else str(ist_today)

    # Calculate longest streak up to max(ist_today, utc_today)
    horizon = max(ist_today, utc_today)
    all_sorted = sorted(d for d in all_days if d <= str(horizon))

    longest = 0
    longest_start = None
    longest_end = None
    run = 0
    run_start = None
    prev_dt: date | None = None

    for d_str in all_sorted:
        cur_dt = date.fromisoformat(d_str)
        cnt = all_days[d_str]
        if cnt > 0:
            if run == 0 or (prev_dt is not None and (cur_dt - prev_dt).days != 1):
                run = 1
                run_start = d_str
            else:
                run += 1
            if run >= longest:
                longest = run
                longest_start = run_start
                longest_end = d_str
        else:
            run = 0
            run_start = None
        prev_dt = cur_dt

    # Calculate current active streak (gracefully handles pre-commit hours in IST/UTC)
    today_commits = all_days.get(str(ist_today), 0)
    anchor_date = ist_today
    today_locked = today_commits > 0

    if not today_locked:
        # Check UTC today just in case, then yesterday
        if all_days.get(str(utc_today), 0) > 0:
            anchor_date = utc_today
            today_commits = all_days[str(utc_today)]
            today_locked = True
        elif all_days.get(str(ist_today - timedelta(days=1)), 0) > 0:
            anchor_date = ist_today - timedelta(days=1)
        elif all_days.get(str(utc_today - timedelta(days=1)), 0) > 0:
            anchor_date = utc_today - timedelta(days=1)
        else:
            anchor_date = None

    current_streak = 0
    current_start = None
    current_end = None

    if anchor_date is not None:
        current_end = str(anchor_date)
        cursor = anchor_date
        while all_days.get(str(cursor), 0) > 0:
            current_start = str(cursor)
            current_streak += 1
            cursor -= timedelta(days=1)

    # Guard edge case: if current streak beats recorded longest
    if current_streak >= longest and current_streak > 0:
        longest = current_streak
        longest_start = current_start
        longest_end = current_end

    return {
        "username": username,
        "total_contributions": total_contributions,
        "first_active_date": first_active_date,
        "current_streak": current_streak,
        "current_start": current_start,
        "current_end": current_end,
        "longest_streak": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "today_commits": today_commits,
        "today_locked": today_locked,
        "ist_now": ist_now.strftime("%d %b %Y, %H:%M IST"),
        "ist_date": str(ist_today),
    }


def fmt_date(d_str: str | None, include_year: bool = False) -> str:
    if not d_str:
        return "-"
    dt = date.fromisoformat(d_str)
    # Cross-platform no-leading-zero day format
    day_num = str(dt.day)
    if include_year:
        return f"{dt.strftime('%b')} {day_num}, {dt.year}"
    return f"{dt.strftime('%b')} {day_num}"


def fmt_range(start_str: str | None, end_str: str | None) -> str:
    if not start_str or not end_str:
        return "No active streak"
    s_yr = date.fromisoformat(start_str).year
    e_yr = date.fromisoformat(end_str).year
    if s_yr != e_yr:
        return f"{fmt_date(start_str, True)} - {fmt_date(end_str, True)}"
    return f"{fmt_date(start_str, False)} - {fmt_date(end_str, False)}"


def render_svg(stats: dict, theme_name: str = "tokyonight") -> str:
    t = THEMES.get(theme_name, THEMES["tokyonight"])
    total_fmt = f"{stats['total_contributions']:,}"
    total_range = f"{fmt_date(stats['first_active_date'], True)} - Present"

    curr_num = str(stats["current_streak"])
    curr_range = (
        fmt_range(stats["current_start"], stats["current_end"])
        if stats["current_streak"] > 0
        else fmt_date(stats["ist_date"], False)
    )

    long_num = str(stats["longest_streak"])
    long_range = fmt_range(stats["longest_start"], stats["longest_end"])

    if stats["today_locked"]:
        unit = "COMMIT" if stats["today_commits"] == 1 else "COMMITS"
        today_pill = f"TODAY: +{stats['today_commits']} {unit}"
    else:
        today_pill = "STREAK ALIVE • TODAY PENDING"

    footer_status = f"LIVE MONITOR ACTIVE  •  {today_pill}  •  SYNCED {stats['ist_now'].upper()}"

    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' style='isolation: isolate' viewBox='0 0 495 212' width='495px' height='212px' direction='ltr'>
  <style>
    @keyframes currstreak {{
      0% {{ font-size: 3px; opacity: 0.2; }}
      80% {{ font-size: 33px; opacity: 1; }}
      100% {{ font-size: 28px; opacity: 1; }}
    }}
    @keyframes fadein {{
      0% {{ opacity: 0; }}
      100% {{ opacity: 1; }}
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.35; }}
    }}
  </style>
  <defs>
    <clipPath id='outer_rectangle'>
      <rect width='495' height='212' rx='6' />
    </clipPath>
    <mask id='mask_out_ring_behind_fire'>
      <rect width='495' height='212' fill='white' />
      <ellipse id='mask-ellipse' cx='247.5' cy='31' rx='13' ry='17' fill='black' />
    </mask>
  </defs>

  <g clip-path='url(#outer_rectangle)'>
    <!-- Card Background -->
    <rect fill='{t["bg"]}' x='0' y='0' width='495' height='212' />
    <!-- Top Accent Line -->
    <rect x='0' y='0' width='495' height='3' fill='{t["accent_bar"]}' opacity='0.9' />

    <!-- Column Dividers -->
    <line x1='165' y1='26' x2='165' y2='166' stroke='{t["stroke"]}' stroke-width='1' opacity='0.65' />
    <line x1='330' y1='26' x2='330' y2='166' stroke='{t["stroke"]}' stroke-width='1' opacity='0.65' />

    <!-- LEFT COLUMN: Total Contributions -->
    <g transform='translate(82.5, 46)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["side_nums"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='700' font-size='28px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.4s'>{total_fmt}</text>
    </g>
    <g transform='translate(82.5, 83)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["side_labels"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='600' font-size='14px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.5s'>Total Contributions</text>
    </g>
    <g transform='translate(82.5, 113)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["dates"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='400' font-size='11.5px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.6s'>{total_range}</text>
    </g>

    <!-- CENTER COLUMN: Current Streak -->
    <g transform='translate(247.5, 46)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["curr_num"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='700' font-size='28px' style='animation: currstreak 0.6s linear forwards'>{curr_num}</text>
    </g>
    <g transform='translate(247.5, 106)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["curr_label"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='700' font-size='14px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.7s'>Current Streak</text>
    </g>
    <g transform='translate(247.5, 134)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["dates"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='400' font-size='11.5px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.8s'>{curr_range}</text>
    </g>

    <!-- Flame Ring -->
    <g mask='url(#mask_out_ring_behind_fire)'>
      <circle cx='247.5' cy='70' r='40' fill='none' stroke='{t["ring"]}' stroke-width='5' style='opacity: 0; animation: fadein 0.5s linear forwards 0.3s' />
    </g>
    <!-- Flame Icon -->
    <g transform='translate(247.5, 19)' style='opacity: 0; animation: fadein 0.5s linear forwards 0.4s'>
      <path d='M -12 -0.5 L 15 -0.5 L 15 23.5 L -12 23.5 L -12 -0.5 Z' fill='none' />
      <path d='M 1.5 0.67 C 1.5 0.67 2.24 3.32 2.24 5.47 C 2.24 7.53 0.89 9.2 -1.17 9.2 C -3.23 9.2 -4.79 7.53 -4.79 5.47 L -4.76 5.11 C -6.78 7.51 -8 10.62 -8 13.99 C -8 18.41 -4.42 22 0 22 C 4.42 22 8 18.41 8 13.99 C 8 8.6 5.41 3.79 1.5 0.67 Z M -0.29 19 C -2.07 19 -3.51 17.6 -3.51 15.86 C -3.51 14.24 -2.46 13.1 -0.7 12.74 C 1.07 12.38 2.9 11.53 3.92 10.16 C 4.31 11.45 4.51 12.81 4.51 14.2 C 4.51 16.85 2.36 19 -0.29 19 Z' fill='{t["fire"]}' />
    </g>

    <!-- RIGHT COLUMN: Longest Streak -->
    <g transform='translate(412.5, 46)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["side_nums"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='700' font-size='28px' style='opacity: 0; animation: fadein 0.5s linear forwards 0.9s'>{long_num}</text>
    </g>
    <g transform='translate(412.5, 83)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["side_labels"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='600' font-size='14px' style='opacity: 0; animation: fadein 0.5s linear forwards 1.0s'>Longest Streak</text>
    </g>
    <g transform='translate(412.5, 113)'>
      <text x='0' y='32' text-anchor='middle' fill='{t["dates"]}' font-family='"Segoe UI", Ubuntu, -apple-system, sans-serif' font-weight='400' font-size='11.5px' style='opacity: 0; animation: fadein 0.5s linear forwards 1.1s'>{long_range}</text>
    </g>

    <!-- LIVE DYNAMIC MONITOR FOOTER -->
    <rect x='0' y='182' width='495' height='30' fill='{t["footer_bg"]}' />
    <line x1='0' y1='182' x2='495' y2='182' stroke='{t["border"]}' stroke-width='1' />
    <circle cx='30' cy='197' r='3.5' fill='{t["live_dot"]}' style='animation: pulse 2s ease-in-out infinite' />
    <text x='253' y='200.5' text-anchor='middle' fill='{t["footer_text"]}' font-family='"Consolas", "Fira Code", monospace' font-weight='600' font-size='9.2px' letter-spacing='0.3'>{footer_status}</text>
  </g>
  <!-- Crisp Rounded Outer Border -->
  <rect stroke='{t["border"]}' stroke-width='1.2' fill='none' rx='6' x='0.6' y='0.6' width='493.8' height='210.8' />
</svg>
"""
    return svg


def purge_github_camo(profile_urls: list[str]) -> None:
    """Find and purge Camo cache URLs for streak SVGs on target GitHub pages."""
    for page_url in profile_urls:
        try:
            req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            imgs = re.findall(r'<img[^>]+>', html)
            for img in imgs:
                if "camo.githubusercontent.com" in img and ("github-streak" in img or "streak" in img.lower()):
                    m = re.search(r'src="([^"]+)"', img)
                    if m:
                        camo_url = m.group(1).replace("&amp;", "&")
                        p_req = urllib.request.Request(camo_url, method="PURGE", headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(p_req, timeout=10) as p_resp:
                            print(f"[CAMO PURGE] {page_url} -> {p_resp.status} {p_resp.read().decode('utf-8', errors='replace').strip()}")
        except Exception as exc:
            print(f"[WARN] Camo purge skipped for {page_url}: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate live GitHub Streak SVG directly from GitHub calendar")
    parser.add_argument("--out-dir", default=".", help="Output directory for generated SVGs & JSON")
    parser.add_argument("--purge", action="store_true", help="Purge GitHub Camo proxy cache after writing")
    parser.add_argument("--purge-only", action="store_true", help="Only purge GitHub Camo cache without regenerating SVGs")
    args = parser.parse_args()

    target_pages = [
        f"https://github.com/{USERNAME}",
        f"https://github.com/{USERNAME}/Data-Engineering-Master-Course",
    ]

    if args.purge_only:
        purge_github_camo(target_pages)
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    stats = collect_contributions(USERNAME, START_YEAR)

    print("Live GitHub Stats Verified:")
    print(f"  Total Contributions : {stats['total_contributions']:,} (Since {stats['first_active_date']})")
    print(f"  Current Streak      : {stats['current_streak']} ({stats['current_start']} to {stats['current_end']})")
    print(f"  Longest Streak      : {stats['longest_streak']} ({stats['longest_start']} to {stats['longest_end']})")
    print(f"  Today IST ({stats['ist_date']}): +{stats['today_commits']} commits (Locked={stats['today_locked']})")

    # Write TokyoNight SVG (primary) and Radical SVG (secondary)
    with open(os.path.join(args.out_dir, "github-streak.svg"), "w", encoding="utf-8") as f:
        f.write(render_svg(stats, "tokyonight"))

    with open(os.path.join(args.out_dir, "github-streak-radical.svg"), "w", encoding="utf-8") as f:
        f.write(render_svg(stats, "radical"))

    with open(os.path.join(args.out_dir, "streak_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    if args.purge:
        purge_github_camo(target_pages)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
