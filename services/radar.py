import asyncio
import datetime
import logging
import time
from typing import Any, Dict, List, Optional

from config import settings
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

logger = logging.getLogger("radar")

# Statuses that count as a disruption the agent must act on.
DISRUPTION_STATES = {
    "CANCELLED",
    "DELAYED",
    "DELAYED_4H",
    "RESCHEDULED",
    "DIVERTED",
    "BOARDING_CLOSED",
    "CANCELLED_BY_CARRIER",
}

# Seeded watchlist so the demo shows autonomous behaviour immediately.
# Dates are always computed (today+2) so the sandbox never scans past dates.
def _default_watchlist() -> List[Dict[str, Any]]:
    d = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    return [
        {"flight_number": "TG303", "date": d},
        {"flight_number": "PG920", "date": d},
        {"flight_number": "FD251", "date": d},
        {"flight_number": "SQ970", "date": d},
    ]


class RescueRadar:
    """Autonomous monitoring loop.

    Watches a flight list, detects disruptions via Atlas (mock now, real ATRIP
    later), and proactively pre-builds a rescue plan for each disruption so the
    passenger only has to approve — not wait on hold.
    """

    def __init__(self, atlas: AtlasClient, engine: RescueEngine):
        self.atlas = atlas
        self.engine = engine
        self.watchlist: List[Dict[str, Any]] = _default_watchlist()
        self.alerts: List[Dict[str, Any]] = []
        self.last_scan: Dict[str, Any] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._seen_keys: set = set()

    # --- watchlist management ----------------------------------------------
    def add_flight(self, flight_number: str, date: str, passenger_name: str = "") -> bool:
        flight_number = (flight_number or "").upper().strip()
        if not flight_number or not date:
            return False
        if any(w["flight_number"] == flight_number and w["date"] == date for w in self.watchlist):
            return False
        self.watchlist.append(
            {"flight_number": flight_number, "date": date, "passenger_name": passenger_name}
        )
        return True

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Rescue Radar started (interval=%ss)", settings.radar_interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.scan()
            except Exception as exc:  # noqa: BLE001 — radar must never crash the app
                logger.warning("radar scan error (%s)", type(exc).__name__)
            await asyncio.sleep(settings.radar_interval_seconds)

    # --- core scan ---------------------------------------------------------
    async def scan(self) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        new_alerts: List[Dict[str, Any]] = []

        for item in self.watchlist:
            try:
                status = await self.atlas.get_flight_status(item["flight_number"], item["date"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("status check failed (%s)", type(exc).__name__)
                status = {"flight_number": item["flight_number"], "status": "UNKNOWN"}

            disrupted = status.get("status") in DISRUPTION_STATES
            results.append(
                {
                    "flight_number": item["flight_number"],
                    "date": item["date"],
                    "status": status.get("status", "UNKNOWN"),
                    "carrier": status.get("carrier"),
                    "reason": status.get("reason"),
                    "disrupted": disrupted,
                    "compensation_usd": status.get("compensation_amount_usd"),
                    "scanned_at": time.time(),
                }
            )

            if disrupted:
                key = f'{item["flight_number"]}:{status.get("status")}'
                if key not in self._seen_keys:
                    # Autonomous action: pre-build the rescue plan before the
                    # passenger even asks. This is the agentic differentiator.
                    plan = None
                    try:
                        plan = await self.engine.handle_disruption(
                            flight_number=item["flight_number"],
                            passenger_name=item.get("passenger_name", ""),
                            date=item["date"],
                            currency="USD",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("proactive plan failed (%s)", type(exc).__name__)

                    alert = {
                        "id": f'al_{item["flight_number"]}_{int(time.time())}',
                        "flight_number": item["flight_number"],
                        "status": status.get("status"),
                        "reason": status.get("reason"),
                        "compensation_usd": status.get("compensation_amount_usd"),
                        "detected_at": time.time(),
                        "rescue_plan": plan,
                    }
                    self.alerts.insert(0, alert)
                    new_alerts.append(alert)
                    self._seen_keys.add(key)
                    logger.info(
                        "RADAR ALERT: %s %s — proactive plan ready",
                        item["flight_number"],
                        status.get("status"),
                    )
            else:
                for k in list(self._seen_keys):
                    if k.startswith(item["flight_number"] + ":"):
                        self._seen_keys.discard(k)

        self.last_scan = {"at": time.time(), "flights": results}
        return {"flights": results, "new_alerts": new_alerts}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "watchlist": self.watchlist,
            "alerts": self.alerts[:20],
            "last_scan": self.last_scan,
            "interval_seconds": settings.radar_interval_seconds,
        }


_radar_instance: Optional[RescueRadar] = None


def get_radar() -> RescueRadar:
    """Process-wide singleton so the background loop runs exactly once."""
    global _radar_instance
    if _radar_instance is None:
        atlas = AtlasClient()
        engine = RescueEngine(atlas)
        _radar_instance = RescueRadar(atlas, engine)
    return _radar_instance
