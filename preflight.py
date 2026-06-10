#!/usr/bin/env python3
"""
Preflight-Check für den Bull-Put-Spread-Bot.

Verbindet sich mit IB Gateway, zeigt alle offenen Orders/Positionen strukturiert an
und kann alte kaputte Orders (Limit 0.00) aufräumen.

Verwendung:
    python preflight.py                          # Nur anzeigen (Dry-Run, ändert nichts)
    python preflight.py --cancel-zero            # Orders mit Limit 0.00 stornieren
    python preflight.py --cancel-all-bags        # ALLE BAG-Orders stornieren (Tabula rasa)
    python preflight.py --port 4002              # anderer Gateway-Port (Paper-Default oft 4002)

WICHTIG: Bot vorher stoppen bzw. anderen clientId nutzen — Default hier ist 77,
damit es nicht mit dem Bot kollidiert.
"""
import argparse
import asyncio
import math

# Python 3.14: kein impliziter Event-Loop beim Import → vor ib_insync setzen
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB


def fmt_price(v):
    if v is None:
        return "    —"
    try:
        if math.isnan(v):
            return "    —"
    except TypeError:
        pass
    return f"{v:8.2f}"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4001,
                    help="IB Gateway Port (Live meist 4001, Paper meist 4002)")
    ap.add_argument("--client-id", type=int, default=77)
    ap.add_argument("--cancel-zero", action="store_true",
                    help="BAG-Orders mit Limit 0.00 stornieren")
    ap.add_argument("--cancel-all-bags", action="store_true",
                    help="ALLE offenen BAG-Orders stornieren (Tabula rasa vor Testlauf)")
    args = ap.parse_args()

    ib = IB()
    try:
        await ib.connectAsync(args.host, args.port, clientId=args.client_id, timeout=10)
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen ({args.host}:{args.port}): {e}")
        print("   → Läuft IB Gateway? Stimmt der Port? (Paper-Gateway oft 4002)")
        return

    accounts = ib.managedAccounts()
    acct = accounts[0] if accounts else "?"
    is_paper = acct.upper().startswith("DU")
    print("=" * 78)
    print(f"  KONTO: {acct}  ({'PAPER ✅' if is_paper else '⚠️  LIVE — Vorsicht!'})")
    print("=" * 78)

    # ── Offene Orders ──────────────────────────────────────────────────────
    trades = await ib.reqAllOpenOrdersAsync()
    await asyncio.sleep(1.0)
    trades = ib.openTrades() or trades

    bags   = [t for t in trades if t.contract.secType == "BAG"]
    others = [t for t in trades if t.contract.secType != "BAG"]

    print(f"\n📋 OFFENE ORDERS: {len(trades)} gesamt, davon {len(bags)} BAG (Spreads)\n")
    if bags:
        print(f"  {'ID':>10}  {'Symbol':<6} {'Akt.':<5} {'Typ':<8} "
              f"{'Limit':>8} {'Stop':>8} {'TIF':<4} {'Parent':>10} {'Status':<14}")
        print("  " + "-" * 88)
        problems = []
        for t in sorted(bags, key=lambda x: (x.contract.symbol, x.order.parentId or 0,
                                             x.order.orderId)):
            o = t.order
            line = (f"  {o.orderId:>10}  {t.contract.symbol:<6} {o.action:<5} "
                    f"{o.orderType:<8} {fmt_price(o.lmtPrice)} {fmt_price(o.auxPrice)} "
                    f"{o.tif:<4} {o.parentId or '—':>10} {t.orderStatus.status:<14}")
            flags = []
            if o.orderType == "LMT" and (o.lmtPrice or 0) == 0:
                flags.append("⚠️ LIMIT 0.00")
            if o.orderType.startswith("STP") and (o.auxPrice or 0) == 0:
                flags.append("⚠️ STOP-TRIGGER 0.00")
            if flags:
                problems.append(t)
                line += "   " + " ".join(flags)
            print(line)

        # ── Bracket-Struktur prüfen: Entry (SELL, kein Parent) + Kinder ────
        print("\n🔍 BRACKET-STRUKTUR:")
        entries = [t for t in bags if not t.order.parentId]
        for e in entries:
            kids = [t for t in bags if t.order.parentId == e.order.orderId]
            tp = [k for k in kids if k.order.orderType == "LMT"]
            sl = [k for k in kids if k.order.orderType.startswith("STP")]
            ok = (e.order.action == "SELL" and e.order.orderType == "LMT"
                  and (e.order.lmtPrice or 0) > 0 and len(tp) == 1 and len(sl) == 1)
            mark = "✅" if ok else ("➖ Einzelorder (kein Bracket)" if not kids else "❌")
            print(f"  {mark} [{e.contract.symbol}] Entry #{e.order.orderId} "
                  f"{e.order.action} LMT {fmt_price(e.order.lmtPrice).strip()} "
                  f"→ {len(tp)} TP / {len(sl)} SL als Kinder")
    else:
        print("  (keine BAG-Orders offen)")

    if others:
        print(f"\n  ℹ️  Außerdem {len(others)} Nicht-BAG-Order(s): "
              f"{[(t.contract.symbol, t.order.action, t.order.orderType) for t in others]}")

    # ── Positionen ─────────────────────────────────────────────────────────
    positions = [p for p in ib.positions() if p.position != 0]
    print(f"\n📊 OFFENE POSITIONEN: {len(positions)}")
    for p in positions:
        c = p.contract
        extra = (f" {c.lastTradeDateOrContractMonth} {c.strike}{c.right}"
                 if c.secType == "OPT" else "")
        print(f"  {c.symbol:<6} {c.secType:<4}{extra}  Stück: {p.position:+.0f}  "
              f"avgCost: {p.avgCost:.2f}")

    # ── Aufräumen ──────────────────────────────────────────────────────────
    to_cancel = []
    if args.cancel_all_bags:
        to_cancel = bags
    elif args.cancel_zero:
        to_cancel = [t for t in bags
                     if (t.order.orderType == "LMT" and (t.order.lmtPrice or 0) == 0)
                     or (t.order.orderType.startswith("STP") and (t.order.auxPrice or 0) == 0)]

    if to_cancel:
        print(f"\n🧹 STORNIERE {len(to_cancel)} Order(s) ...")
        for t in to_cancel:
            try:
                ib.cancelOrder(t.order)
                print(f"  🗑  #{t.order.orderId} ({t.contract.symbol} "
                      f"{t.order.action} {t.order.orderType}) storniert")
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  ⚠️  #{t.order.orderId}: {e}")
        await asyncio.sleep(1.5)
        rest = [t for t in ib.openTrades() if t.contract.secType == "BAG"]
        print(f"  → Verbleibende BAG-Orders: {len(rest)}")
    elif args.cancel_zero:
        print("\n✅ Keine 0.00-Orders gefunden — nichts zu stornieren.")
    else:
        print("\nℹ️  Dry-Run — nichts geändert. Aufräumen mit --cancel-zero "
              "oder --cancel-all-bags.")

    print("\nFertig.")
    ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
