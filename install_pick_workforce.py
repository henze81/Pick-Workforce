"""
install_pick_workforce.py
=========================
Installiert die "Pick Workforce" Karte in UFO-Engine.

Idempotent: überspringt bereits installierte Teile.

Aufruf (aus dem Ordner C:\\UFO-Engine):
    .venv\\Scripts\\python.exe Ufoneues\\install_pick_workforce.py

Voraussetzungen:
  - mwinit -f ausgeführt
  - pip: requests-negotiate-sspi, httpx
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent  # C:\\UFO-Engine
ok = True

def patch_before(path_rel, anchor, insert, check):
    p = ROOT / path_rel
    c = p.read_text(encoding="utf-8")
    if check in c:
        print(f"  SKIP {path_rel}: bereits vorhanden"); return
    if anchor not in c:
        print(f"  FEHLER {path_rel}: Ankerpunkt nicht gefunden"); global ok; ok = False; return
    p.write_text(c.replace(anchor, insert + anchor, 1), encoding="utf-8")
    print(f"  OK   {path_rel}")

def patch_after(path_rel, anchor, insert, check):
    p = ROOT / path_rel
    c = p.read_text(encoding="utf-8")
    if check in c:
        print(f"  SKIP {path_rel}: bereits vorhanden"); return
    if anchor not in c:
        print(f"  FEHLER {path_rel}: Ankerpunkt nicht gefunden"); global ok; ok = False; return
    p.write_text(c.replace(anchor, anchor + insert, 1), encoding="utf-8")
    print(f"  OK   {path_rel}")

def append_to(path_rel, content, check):
    p = ROOT / path_rel
    c = p.read_text(encoding="utf-8")
    if check in c:
        print(f"  SKIP {path_rel}: bereits vorhanden"); return
    p.write_text(c.rstrip() + "\n\n\n" + content, encoding="utf-8")
    print(f"  OK   {path_rel}")

def replace_block(path_rel, old_block, new_block, check):
    p = ROOT / path_rel
    c = p.read_text(encoding="utf-8")
    if check in c:
        print(f"  SKIP {path_rel}: bereits vorhanden"); return
    if old_block not in c:
        print(f"  FEHLER {path_rel}: Alter Block nicht gefunden"); global ok; ok = False; return
    p.write_text(c.replace(old_block, new_block, 1), encoding="utf-8")
    print(f"  OK   {path_rel}")

print("Pick Workforce Installer")
print("========================")

# ── Code-Blöcke ────────────────────────────────────────────────────────

URL_DAY_FUNC = 'def _url_day(process_id: int, start_str: str, end_str: str | None = None) -> str:\n    """Build FCLM functionRollup URL for a day range.\n    start_str/end_str: \'YYYY/MM/DD\'. end defaults to start (single day)."""\n    from urllib.parse import quote\n    if end_str is None:\n        end_str = start_str\n    return (\n        f"{FCLM_BASE}/reports/functionRollup"\n        f"?reportFormat=CSV&warehouseId={_get_ob_fc_id()}"\n        f"&processId={process_id}"\n        f"&spanType=Day&startDate={quote(start_str, safe=\'\')}&endDate={quote(end_str, safe=\'\')}"\n        f"{_TAIL}"\n    )\n'

TODAY_FUNCS = '# ── Today\'s Transfer Out Pick — live intraday rollup ──────────────────────────\n\ndef _current_shift_dates() -> tuple[str, str | None]:\n    """\n    Return (start_date_str, end_date_str|None) for the active shift window.\n    Shift boundaries (Berlin time):\n      ES  06:00 – 14:15  → today only\n      LS  14:15 – 22:30  → today only\n      NS  22:30 – 06:00  → spans midnight:\n            before 06:00 → yesterday + today (two fetches, merge)\n            after  22:30 → today only (NS just started)\n    """\n    from datetime import timedelta\n    from backend.services.berlin_time import now_berlin\n    now = now_berlin()\n    h, m = now.hour, now.minute\n    today_str = now.date().strftime("%Y/%m/%d")\n    # NS tail: 00:00 – 06:00 belongs to the NS that started yesterday\n    if (h, m) < (6, 0):\n        yesterday_str = (now.date() - timedelta(days=1)).strftime("%Y/%m/%d")\n        return yesterday_str, today_str   # two-day merge needed\n    # NS head: 22:30 – 00:00 — NS just started, data is on today only\n    return today_str, None                # single day\n\n\ndef fetch_today_pick() -> list[dict]:\n    """\n    Fetch FCLM functionRollup for \'Transfer Out Pick\' for the active shift window.\n    Shift windows (Berlin):  ES 06-14:15 | LS 14:15-22:30 | NS 22:30-06:00.\n    NS spans midnight: fetches yesterday + today and merges per employee.\n    """\n    process_id = PROCESSES["Transfer Out Pick"]  # 1003065\n    cookies = _load_cookies()\n    if not cookies:\n        log.warning("fetch_today_pick: no Midway cookies — run mwinit -f")\n        return []\n\n    def _fetch_one(date_str: str) -> list[dict]:\n        url = _url_day(process_id, date_str)\n        try:\n            with httpx.Client(\n                cookies=cookies, timeout=30, verify=False,\n                follow_redirects=True, headers={"User-Agent": "UFO-Hosting/1.0"},\n            ) as client:\n                r = client.get(url)\n                r.raise_for_status()\n                return _parse_csv("Transfer Out Pick", process_id, r.text)\n        except Exception as exc:\n            log.warning("fetch_today_pick(%s) error: %s", date_str, exc)\n            return []\n\n    start_str, end_str = _current_shift_dates()\n\n    if end_str is None:\n        # ES or LS or NS head — single day is enough\n        return _fetch_one(start_str)\n\n    # NS tail (before 06:00) — merge yesterday + today\n    merged: dict[str, dict] = {}\n    for rec in _fetch_one(start_str) + _fetch_one(end_str):\n        eid = rec["employee_id"]\n        if eid not in merged:\n            merged[eid] = rec.copy()\n        else:\n            prev = merged[eid]\n            prev["hours"]      = round((prev["hours"] or 0) + (rec["hours"] or 0), 4)\n            prev["units"]      = (prev["units"]      or 0) + (rec["units"]      or 0)\n            prev["case_units"] = (prev["case_units"] or 0) + (rec["case_units"] or 0)\n            h = prev["hours"]\n            prev["uph"]      = round(prev["units"]      / h, 2) if h else None\n            prev["case_uph"] = round(prev["case_units"] / h, 2) if h else None\n    return list(merged.values())\n'

ENDPOINT = '# -- Pick Workforce FCLM Rollup (today\'s Cases + Each Total per AA) ----------\n\n@router.get("/pick-workforce-rollup")\ndef get_pick_workforce_rollup():\n    """Today\'s FCLM functionRollup for Transfer Out Pick.\n    Returns dict keyed by employee_id: {cases, each_total}.\n    Refreshed by frontend every 10 min."""\n    from backend.services.function_rollup_service import fetch_today_pick\n    records = fetch_today_pick()\n    result: dict = {}\n    for r in records:\n        emp_id = r.get(\'employee_id\', \'\')\n        if not emp_id:\n            continue\n        entry = {\n            \'each_units\': r.get(\'units\'),       # EACH-Total Units\n            \'case_units\': r.get(\'case_units\'),   # Cases Units\n            \'case_uph\':   r.get(\'case_uph\'),     # Cases UPH\n        }\n        result[emp_id] = entry\n        # Also index without leading zeros (Picking Console returns int-style IDs)\n        if emp_id.isdigit():\n            stripped = str(int(emp_id))\n            if stripped != emp_id:\n                result[stripped] = entry\n    return result\n'

HOOK = "// -- Pick Workforce FCLM Rollup (Cases + Each Total per AA, today) -----------\n\nexport interface PickRollupEntry {\n  each_units: number | null   // EACH-Total Units\n  case_units: number | null   // Cases Units\n  case_uph:   number | null   // Cases UPH\n}\n\nexport const usePickWorkforceRollup = () =>\n  useQuery<Record<string, PickRollupEntry>>({\n    queryKey: ['pick-workforce-rollup-v2'],\n    queryFn:  () => api.get('/overview/pick-workforce-rollup').then(r => r.data),\n    staleTime: 600_000,\n    refetchInterval: 600_000,\n  })\n"

CARD_BLOCK = '{/* Pick Workforce -- individual pickers per process path from Picking Console */}\n              <div className="card space-y-3">\n                <div className="flex items-center justify-between">\n                  <div className="flex items-center gap-2">\n                    <h2 className="section-title mb-0">Pick Workforce</h2>\n                    <span className="text-slate-400 text-xs tabular-nums">\n                      {(pickerData?.paths ?? [])\n                        .flatMap(p => (p.aa ?? []).filter((a: any) => a.login && a.login !== \'?\'))\n                        .filter((a: any) => {\n                          const isPT = a.pick_area?.startsWith(\'PT\')\n                          if (pickHall === \'h1\') return !!isPT\n                          if (pickHall === \'h3\') return !isPT\n                          return true\n                        }).length} Picker\n                    </span>\n                  </div>\n                  <a href="https://picking-console.eu.picking.aft.a2z.com/fc/DRS8/pick-workforce"\n                    target="_blank" rel="noreferrer" className="text-[10px] text-cyan-600 hover:underline"\n                  >Picking Console ↗</a>\n                </div>\n                {(() => {\n                  // Flatten all AA entries, filter by pickArea:\n                  // pickArea starting with "PT" -> H1, everything else (HR-D etc.) -> H3\n                  const rows = (pickerData?.paths ?? [])\n                    .flatMap(p =>\n                      p.aa\n                        .filter(a => a.login && a.login !== \'?\')\n                        .map(a => ({ ...a, pp: p.pp }))\n                    )\n                    .filter(a => {\n                      const isPT = a.pick_area?.startsWith(\'PT\')\n                      if (pickHall === \'h1\') return !!isPT\n                      if (pickHall === \'h3\') return !isPT\n                      return true\n                    })\n                  if (!rows.length) return (\n                    <div className="text-xs text-slate-500 py-2 text-center">Keine aktiven Picker</div>\n                  )\n                  const fmtTime = (ts: string | null | undefined) => {\n                    if (!ts) return \'—\'\n                    try { return new Date(ts).toLocaleTimeString(\'de-DE\', { hour: \'2-digit\', minute: \'2-digit\', second: \'2-digit\' }) }\n                    catch { return ts }\n                  }\n                  return (\n                    <table className="w-full text-xs">\n                      <thead>\n                        <tr className="text-slate-400 border-b border-slate-700 text-[11px]">\n                          <th className="text-left py-1 font-normal">User ID</th>\n                          <th className="text-left py-1 font-normal pl-2">Name</th>\n                          <th className="text-left py-1 font-normal pl-2">Process Path</th>\n                          <th className="text-left py-1 font-normal pl-2">Location</th>\n                          <th className="text-left py-1 font-normal pl-2">Pick Area</th>\n                          <th className="text-left py-1 font-normal pl-2">Last Activity</th>\n                          <th className="text-right py-1 font-normal pl-2">Each</th>\n                          <th className="text-right py-1 font-normal pl-2">Cases</th>\n                          <th className="text-right py-1 font-normal pl-2">Case/h</th>\n                        </tr>\n                      </thead>\n                      <tbody>\n                        {rows.map((a, i) => (\n                          <tr key={`${a.pp}-${a.login}-${i}`} className="border-b border-slate-800/60 hover:bg-slate-800/30">\n                            <td className="py-1 flex items-center gap-1">\n                              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${a.active === false ? \'bg-slate-600\' : \'bg-emerald-400\'}`} title={a.active === false ? \'Inactive\' : \'Active\'} />\n                              <a href={`https://fclm-portal.amazon.com/employee/timeDetails?warehouseId=DRS8&employeeId=${a.employee_id || a.login}`}\n                                target="_blank" rel="noreferrer" className="font-mono text-cyan-400 hover:underline"\n                              >{a.login}</a>\n                            </td>\n                            <td className="py-1 pl-2 text-slate-300">{a.name ?? \'—\'}</td>\n                            <td className="py-1 pl-2 font-mono text-slate-400 text-[11px]">{a.pp.replace(\'PPTrans\', \'\')}</td>\n                            <td className="py-1 pl-2 text-slate-400">{a.location ?? \'—\'}</td>\n                            <td className="py-1 pl-2 text-slate-400 font-mono text-[11px]">{a.pick_area ?? \'—\'}</td>\n                            <td className="py-1 pl-2 text-slate-500 tabular-nums">{fmtTime(a.last_activity_time)}</td>\n                            {(() => {\n                              const r = rollupData?.[a.employee_id]\n                              const fmt = (v: number | null | undefined) =>\n                                v != null ? v.toLocaleString(\'de-DE\') : <span className="text-slate-600">—</span>\n                              return (<>\n                                <td className="py-1 pl-2 text-right tabular-nums text-slate-300">{fmt(r?.each_units)}</td>\n                                <td className="py-1 pl-2 text-right tabular-nums text-slate-300">{fmt(r?.case_units)}</td>\n                                <td className="py-1 pl-2 text-right tabular-nums text-slate-400">{fmt(r?.case_uph)}</td>\n                              </>)\n                            })()}\n                          </tr>\n                        ))}\n                      </tbody>\n                    </table>\n                  )\n                })()}\n              </div>'

OLD_CARD_ANCHOR = '{/* Pick Workforce -- individual pickers per process path from Picking Console */}'


# ── 1. _url_day in function_rollup_service.py ──────────────────────────
print("\n1. _url_day (function_rollup_service.py)")
patch_before(
    "backend/services/function_rollup_service.py",
    "\ndef _url(process_id: int, month: str) -> str:",
    "\n" + URL_DAY_FUNC,
    "_url_day",
)

# ── 2. fetch_today_pick in function_rollup_service.py ───────────────────
print("2. fetch_today_pick (function_rollup_service.py)")
append_to(
    "backend/services/function_rollup_service.py",
    TODAY_FUNCS,
    "fetch_today_pick",
)

# ── 3. /pick-workforce-rollup Endpoint in overview.py ───────────────────
print("3. /pick-workforce-rollup Endpoint (overview.py)")
patch_before(
    "backend/routers/overview.py",
    "# -- DRS8 All Process Paths (Pick Console)",
    ENDPOINT,
    "pick-workforce-rollup",
)

# ── 4. usePickWorkforceRollup Hook in useOverview.ts ────────────────────
print("4. usePickWorkforceRollup Hook (useOverview.ts)")
patch_before(
    "frontend/src/api/hooks/useOverview.ts",
    "// -- Pick Volume by PP (prio/not-prio per pick type)",
    HOOK,
    "usePickWorkforceRollup",
)

# ── 5. Import in OBOverview.tsx ─────────────────────────────────────────
print("5. Import (OBOverview.tsx)")
patch_before(
    "frontend/src/pages/OBOverview.tsx",
    "} from '@/api/hooks/useOverview'",
    "  usePickWorkforceRollup,\n",
    "usePickWorkforceRollup",
)

# ── 6. Hook-Call in OBOverview.tsx ──────────────────────────────────────
print("6. Hook-Call (OBOverview.tsx)")
patch_after(
    "frontend/src/pages/OBOverview.tsx",
    "  const { data: pickerData } = usePickerCounts()",
    "\n  const { data: rollupData } = usePickWorkforceRollup()",
    "rollupData",
)

# ── 7. Pick Workforce Karte in OBOverview.tsx ───────────────────────────
print("7. Pick Workforce Karte (OBOverview.tsx)")
# Findet den alten Karten-Block und ersetzt ihn mit dem neuen
tsx_path = ROOT / "frontend/src/pages/OBOverview.tsx"
tsx_c = tsx_path.read_text(encoding="utf-8")
if "rollupData?.[a.employee_id]" in tsx_c:
    print("  SKIP OBOverview.tsx: Karte bereits vollständig")
else:
    # Finde alten Kartenblock (Ende = vor Live Rates card)
    start = tsx_c.find("{/* Pick Workforce")
    live = tsx_c.find('\n\n              <div className="card space-y-3">\n\n                <h2 className="section-title mb-0">Live Rates', start)
    if start == -1 or live == -1:
        print("  FEHLER OBOverview.tsx: Kartenblock nicht gefunden")
        ok = False
    else:
        tsx_path.write_text(tsx_c[:start] + CARD_BLOCK + tsx_c[live:], encoding="utf-8")
        print("  OK   OBOverview.tsx")


# ── 8. function_rollup_service.py: _url_intraday + _current_shift_window ─────
print("\n8. _url_intraday + _current_shift_window (function_rollup_service.py)")
replace_block(
    "backend/services/function_rollup_service.py",
    "# ── CSV parser ────────────────────────────────────────────────────────────────\n\ndef _parse_csv",
    "def _url_intraday(\n"
    "    process_id: int,\n"
    "    start_date: str, start_h: int, start_m: int,\n"
    "    end_date:   str, end_h:   int, end_m:   int,\n"
    ") -> str:\n"
    '    """Build FCLM functionRollup URL for an Intraday (shift-window) range.\n'
    "    Matches the FCLM UI intraday URL format exactly.\n"
    "    start_date/end_date: 'YYYY/MM/DD'.\"\"\"\n"
    "    from urllib.parse import quote\n"
    "    sd = quote(start_date, safe='')\n"
    "    ed = quote(end_date,   safe='')\n"
    "    return (\n"
    '        f"{FCLM_BASE}/reports/functionRollup"\n'
    '        f"?reportFormat=CSV&warehouseId={_get_ob_fc_id()}"\n'
    '        f"&processId={process_id}"\n'
    '        f"&maxIntradayDays=1"\n'
    '        f"&spanType=Intraday"\n'
    '        f"&startDateIntraday={sd}"\n'
    '        f"&startHourIntraday={start_h}&startMinuteIntraday={start_m}"\n'
    '        f"&endDateIntraday={ed}"\n'
    '        f"&endHourIntraday={end_h}&endMinuteIntraday={end_m}"\n'
    '        f"&startHourIntraday1=0&startMinuteIntraday1=0"\n'
    '        f"&startHourIntraday2=0&startMinuteIntraday2=0"\n'
    '        f"&startHourIntraday3=0&startMinuteIntraday3=0"\n'
    '        f"&startHourIntraday4=0&startMinuteIntraday4=0"\n'
    '        f"&startHourIntraday5=0&startMinuteIntraday5=0"\n'
    '        f"&startHourIntraday6=0&startMinuteIntraday6=0"\n'
    "    )\n"
    "\n"
    "\n"
    "def _current_shift_window() -> tuple[str, int, int, str, int, int]:\n"
    '    """Return (start_date, start_h, start_m, end_date, end_h, end_m) for the active shift.\n'
    "    Shift boundaries (Berlin):\n"
    "      ES  06:00 - 14:15\n"
    "      LS  14:15 - 22:30\n"
    "      NS  22:30 - 06:00 (next day)\n"
    '    """\n'
    "    from datetime import timedelta\n"
    "    from backend.services.berlin_time import now_berlin\n"
    "    now   = now_berlin()\n"
    "    h, m  = now.hour, now.minute\n"
    "    today     = now.date()\n"
    '    today_str     = today.strftime("%Y/%m/%d")\n'
    '    tomorrow_str  = (today + timedelta(days=1)).strftime("%Y/%m/%d")\n'
    '    yesterday_str = (today - timedelta(days=1)).strftime("%Y/%m/%d")\n'
    "\n"
    "    if (h, m) < (6, 0):\n"
    "        # NS tail: 00:00-06:00 -> NS started yesterday 22:30\n"
    "        return yesterday_str, 22, 30, today_str, 6, 0\n"
    "    elif (h, m) < (14, 15):\n"
    "        # ES: 06:00-14:15\n"
    "        return today_str, 6, 0, today_str, 14, 15\n"
    "    elif (h, m) < (22, 30):\n"
    "        # LS: 14:15-22:30\n"
    "        return today_str, 14, 15, today_str, 22, 30\n"
    "    else:\n"
    "        # NS head: 22:30 onward -> ends 06:00 next day\n"
    "        return today_str, 22, 30, tomorrow_str, 6, 0\n"
    "\n"
    "\n"
    "# ── CSV parser ────────────────────────────────────────────────────────────────\n\ndef _parse_csv",
    "_url_intraday",
)

# ── 9. function_rollup_service.py: fetch_today_pick → Intraday ───────────────
print("\n9. fetch_today_pick Intraday-Umbau (function_rollup_service.py)")
replace_block(
    "backend/services/function_rollup_service.py",
    "    def _fetch_one(date_str: str) -> list[dict]:\n"
    "        url = _url_day(process_id, date_str)\n"
    "        try:\n"
    "            with httpx.Client(\n"
    '                cookies=cookies, timeout=30, verify=False,\n'
    '                follow_redirects=True, headers={"User-Agent": "UFO-Hosting/1.0"},\n'
    "            ) as client:\n"
    "                r = client.get(url)\n"
    "                r.raise_for_status()\n"
    '                return _parse_csv("Transfer Out Pick", process_id, r.text)\n'
    "        except Exception as exc:\n"
    '            log.warning("fetch_today_pick(%s) error: %s", date_str, exc)\n'
    "            return []\n"
    "\n"
    "    start_str, end_str = _current_shift_dates()\n"
    "\n"
    "    if end_str is None:\n"
    "        # ES or LS or NS head -- single day is enough\n"
    "        return _fetch_one(start_str)\n"
    "\n"
    "    # NS tail (before 06:00) -- merge yesterday + today\n"
    "    merged: dict[str, dict] = {}\n"
    "    for rec in _fetch_one(start_str) + _fetch_one(end_str):\n"
    '        eid = rec["employee_id"]\n'
    "        if eid not in merged:\n"
    "            merged[eid] = rec.copy()\n"
    "        else:\n"
    "            prev = merged[eid]\n"
    '            prev["hours"]      = round((prev["hours"] or 0) + (rec["hours"] or 0), 4)\n'
    '            prev["units"]      = (prev["units"]      or 0) + (rec["units"]      or 0)\n'
    '            prev["case_units"] = (prev["case_units"] or 0) + (rec["case_units"] or 0)\n'
    '            h = prev["hours"]\n'
    '            prev["uph"]      = round(prev["units"]      / h, 2) if h else None\n'
    '            prev["case_uph"] = round(prev["case_units"] / h, 2) if h else None\n'
    "    return list(merged.values())",
    "    start_date, start_h, start_m, end_date, end_h, end_m = _current_shift_window()\n"
    "    url = _url_intraday(process_id, start_date, start_h, start_m, end_date, end_h, end_m)\n"
    "    try:\n"
    "        with httpx.Client(\n"
    '            cookies=cookies, timeout=30, verify=False,\n'
    '            follow_redirects=True, headers={"User-Agent": "UFO-Hosting/1.0"},\n'
    "        ) as client:\n"
    "            r = client.get(url)\n"
    "            r.raise_for_status()\n"
    '            return _parse_csv("Transfer Out Pick", process_id, r.text)\n'
    "    except Exception as exc:\n"
    '        log.warning("fetch_today_pick error: %s", exc)\n'
    "        return []",
    "_current_shift_window()",
)


# ── Ergebnis ────────────────────────────────────────────────────────────
print()
if ok:
    print("✓ Installation erfolgreich!")
    print("  → Backend neu starten")
    print("  → Browser Hard-Refresh (Strg+Shift+R)")
else:
    print("✗ Es gab Fehler — siehe oben")
    sys.exit(1)
