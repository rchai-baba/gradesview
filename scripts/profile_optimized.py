"""
Profile an optimized approach:
1. Single login, clone cookies to N pool clients (no re-login)
2. Parallel class list fetches
3. current_period_only = only 7 work items instead of 28
"""
import asyncio
import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import httpx

from scraper import (
    async_login, async_get_gradebook_config, async_get_class_list,
    async_load_class_control, async_get_class_grades,
    _get_focus_info,
    BASE_URL, JSON_HEADERS, BROWSER_HEADERS, LOGIN_URL,
)

USERNAME = "chaichai28@midlandps.org"
PASSWORD = "Huta&%Nanjing78"


async def clone_session(source: httpx.AsyncClient, n: int) -> list[httpx.AsyncClient]:
    """Create N new httpx clients that share the source's cookies (no re-login)."""
    clients = []
    for _ in range(n):
        c = httpx.AsyncClient(timeout=30)
        # Copy cookies from the authenticated source
        for name, value in source.cookies.items():
            c.cookies.set(name, value, domain="mi-mps.edupoint.com")
        clients.append(c)
    return clients


async def profile_optimized():
    t0 = time.perf_counter()

    # Phase 1: Single login
    main_client = httpx.AsyncClient(timeout=30)
    t1 = time.perf_counter()
    await async_login(USERNAME, PASSWORD, main_client)
    t2 = time.perf_counter()
    print(f"[Phase 1] Login: {t2 - t1:.2f}s")

    # Phase 2: Get gradebook config
    t3 = time.perf_counter()
    focus_data = await async_get_gradebook_config(main_client)
    t4 = time.perf_counter()
    print(f"[Phase 2] GradebookConfig: {t4 - t3:.2f}s")

    student_gu = focus_data.get("_studentGU", "0")
    school = focus_data["Schools"][0]
    all_periods = school.get("GradingPeriods", [])
    regular_periods = [gp for gp in all_periods if gp.get("GroupName") == "Regular"]
    if not regular_periods:
        regular_periods = all_periods

    # Get just the default period for "current_period_only" mode
    default_gp = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
    print(f"  Default period: {default_gp['Name']}")
    print(f"  All periods: {[gp['Name'] for gp in regular_periods]}")

    # Phase 3: Clone sessions (no login needed!) 
    POOL_SIZE = 6
    t5 = time.perf_counter()
    pool_clients = await clone_session(main_client, POOL_SIZE)
    t6 = time.perf_counter()
    print(f"[Phase 3] Clone {POOL_SIZE} sessions (cookie copy): {(t6 - t5)*1000:.1f}ms")

    # Phase 4: Get class list for default period only
    t7 = time.perf_counter()
    fake_school = {**school, "GradingPeriods": [default_gp]}
    fake_focus = {**focus_data, "Schools": [fake_school]}
    res = await async_get_class_list(main_client, fake_focus)
    t8 = time.perf_counter()
    classes = res["classes"]
    focus_key = res["focus_key"]
    focus_info = res["focus_info"]
    print(f"[Phase 4] ClassList (default period): {t8 - t7:.2f}s  ({len(classes)} classes)")

    # Phase 5: Fetch all classes in parallel using cloned pool
    work_items = list(classes)  # 7 items
    class_timings = []
    available = asyncio.Queue()
    # Add main client + pool clients
    available.put_nowait(main_client)
    for c in pool_clients:
        available.put_nowait(c)

    async def worker():
        while work_items:
            try:
                cls = work_items.pop()
            except IndexError:
                break
            client = await available.get()
            try:
                ts = time.perf_counter()
                title_map = await async_load_class_control(client, focus_info, cls, student_gu, focus_key)
                t_lc = time.perf_counter()
                raw = await async_get_class_grades(client, focus_key)
                t_gc = time.perf_counter()
                class_timings.append({
                    "class": cls.get("Name", "?"),
                    "total": t_gc - ts,
                    "loadcontrol": t_lc - ts,
                    "getclassdata": t_gc - t_lc,
                })
            except Exception as e:
                class_timings.append({
                    "class": cls.get("Name", "?"),
                    "error": str(e),
                })
            finally:
                available.put_nowait(client)

    t9 = time.perf_counter()
    # Launch workers = pool size
    await asyncio.gather(*(worker() for _ in range(POOL_SIZE + 1)))
    t10 = time.perf_counter()

    # Cleanup
    for c in pool_clients:
        await c.aclose()
    await main_client.aclose()

    print(f"[Phase 5] Class data fetch (wall clock): {t10 - t9:.2f}s")
    print()
    print("PER-CLASS TIMINGS:")
    print(f"{'LoadCtrl':>8} {'GetData':>8} {'Total':>8}  Class Name")
    print("-" * 60)
    for ct in sorted(class_timings, key=lambda x: x.get("total", 0), reverse=True):
        if "error" in ct:
            print(f"{'ERR':>8} {'ERR':>8} {'ERR':>8}  {ct['class'][:40]}  ({ct['error'][:50]})")
        else:
            print(f"{ct['loadcontrol']:>7.2f}s {ct['getclassdata']:>7.2f}s {ct['total']:>7.2f}s  {ct['class'][:40]}")

    total = time.perf_counter() - t0
    print()
    print("=" * 60)
    print(f"TOTAL WALL CLOCK: {total:.2f}s")
    print(f"  Login:           {t2-t1:.2f}s")
    print(f"  GBConfig:        {t4-t3:.2f}s")
    print(f"  Clone sessions:  {(t6-t5)*1000:.1f}ms")
    print(f"  ClassList:       {t8-t7:.2f}s")
    print(f"  Class data:      {t10-t9:.2f}s")


if __name__ == "__main__":
    asyncio.run(profile_optimized())
