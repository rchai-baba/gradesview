"""
Profile the full sync to figure out where all the time is going.
Measures each phase: login, config, class-list, pool-init, per-class fetches.
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import httpx

# Import scraper internals
from scraper import (
    async_login, async_get_gradebook_config, async_get_class_list,
    async_load_class_control, async_get_class_grades,
    _get_focus_info, AsyncSessionPool,
    BASE_URL, JSON_HEADERS,
)

USERNAME = "chaichai28@midlandps.org"
PASSWORD = "Huta&%Nanjing78"


async def profile():
    t0 = time.perf_counter()

    # Phase 1: Login
    print("=" * 60)
    main_client = httpx.AsyncClient(timeout=30)
    t1 = time.perf_counter()
    await async_login(USERNAME, PASSWORD, main_client)
    t2 = time.perf_counter()
    print(f"[Phase 1] Login: {t2 - t1:.2f}s")

    # Phase 2: Get gradebook config (studentGU + GBFocusData)
    t3 = time.perf_counter()
    focus_data = await async_get_gradebook_config(main_client)
    t4 = time.perf_counter()
    print(f"[Phase 2] GradebookConfig: {t4 - t3:.2f}s")

    student_gu = focus_data.get("_studentGU", "0")
    schools = focus_data.get("Schools", [])
    school = schools[0]
    all_periods = school.get("GradingPeriods", [])
    regular_periods = [gp for gp in all_periods if gp.get("GroupName") == "Regular"]
    if not regular_periods:
        regular_periods = all_periods
    print(f"  Found {len(regular_periods)} regular grading periods: {[gp['Name'] for gp in regular_periods]}")

    # Phase 3: Get class list for each period (sequential on main client)
    t5 = time.perf_counter()
    period_info = {}
    for gp in regular_periods:
        ts = time.perf_counter()
        fake_school = {**school, "GradingPeriods": [gp]}
        fake_focus = {**focus_data, "Schools": [fake_school]}
        res = await async_get_class_list(main_client, fake_focus)
        te = time.perf_counter()
        period_info[gp["Name"]] = res
        print(f"  ClassList({gp['Name']}): {te - ts:.2f}s  ({len(res['classes'])} classes)")
    t6 = time.perf_counter()
    print(f"[Phase 3] ClassLists (all periods): {t6 - t5:.2f}s")

    # Count total work items
    work_items = []
    for pname, info in period_info.items():
        for cls in info["classes"]:
            work_items.append((pname, cls, info["focus_info"], info["focus_key"]))
    print(f"  Total work items (class×period): {len(work_items)}")

    # Phase 4: Initialize session pool
    pool_size = min(len(work_items), 4)
    t7 = time.perf_counter()
    pool = AsyncSessionPool(USERNAME, PASSWORD, size=pool_size)
    await pool.initialize()
    t8 = time.perf_counter()
    print(f"[Phase 4] Pool init ({pool_size} sessions): {t8 - t7:.2f}s")

    # Phase 5: Fetch each class (LoadControl + GetClassData)
    class_timings = []

    async def worker():
        while work_items:
            try:
                pname, cls, focus_info, focus_key = work_items.pop()
            except IndexError:
                break

            client = await pool.acquire()
            try:
                ts = time.perf_counter()
                
                ts_lc = time.perf_counter()
                title_map = await async_load_class_control(client, focus_info, cls, student_gu, focus_key)
                te_lc = time.perf_counter()
                
                ts_gc = time.perf_counter()
                raw = await async_get_class_grades(client, focus_key)
                te_gc = time.perf_counter()
                
                te = time.perf_counter()
                class_timings.append({
                    "period": pname,
                    "class": cls.get("Name", "?"),
                    "total": te - ts,
                    "loadcontrol": te_lc - ts_lc,
                    "getclassdata": te_gc - ts_gc,
                })
            except Exception as e:
                class_timings.append({
                    "period": pname,
                    "class": cls.get("Name", "?"),
                    "error": str(e),
                })
            finally:
                await pool.release(client)

    t9 = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(pool_size)))
    t10 = time.perf_counter()
    await pool.close()
    await main_client.aclose()

    print(f"[Phase 5] All class fetches (wall clock): {t10 - t9:.2f}s")
    print()

    # Detailed per-class timings
    print("=" * 60)
    print("PER-CLASS TIMINGS:")
    print(f"{'Period':<8} {'LoadCtrl':>8} {'GetData':>8} {'Total':>8}  Class Name")
    print("-" * 60)
    for ct in sorted(class_timings, key=lambda x: x.get("total", 0), reverse=True):
        if "error" in ct:
            print(f"{ct['period']:<8} {'ERR':>8} {'ERR':>8} {'ERR':>8}  {ct['class'][:40]}  ({ct['error'][:40]})")
        else:
            print(f"{ct['period']:<8} {ct['loadcontrol']:>7.2f}s {ct['getclassdata']:>7.2f}s {ct['total']:>7.2f}s  {ct['class'][:40]}")

    print()
    print("=" * 60)
    total = time.perf_counter() - t0
    print(f"TOTAL WALL CLOCK: {total:.2f}s")
    print(f"  Login:        {t2-t1:.2f}s")
    print(f"  GBConfig:     {t4-t3:.2f}s")
    print(f"  ClassLists:   {t6-t5:.2f}s")
    print(f"  Pool init:    {t8-t7:.2f}s")
    print(f"  Class data:   {t10-t9:.2f}s")

    overhead = total - (t2-t1) - (t4-t3) - (t6-t5) - (t8-t7) - (t10-t9)
    print(f"  Overhead:     {overhead:.2f}s")

if __name__ == "__main__":
    asyncio.run(profile())
