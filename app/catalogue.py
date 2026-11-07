"""Product catalogue + deterministic bundle rule engine.

The advisor (LLM or not) never prices anything. Everything money- or
eligibility-related comes from here, so a judge can read the rules.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Product:
    id: str
    category: str
    name: str
    description: str
    unit: str
    price_min: int
    price_max: int
    setup: int
    min_contract: int
    tiers: List[int]
    min_employees: int
    min_sites: int
    requires_gstin: bool
    requires_one_of: List[str]
    install_days: int
    segments: List[str]


def load_catalogue() -> Dict[str, Product]:
    out: Dict[str, Product] = {}
    with open(DATA / "product_catalogue.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["product_id"]] = Product(
                id=r["product_id"], category=r["category"], name=r["product_name"],
                description=r["description"], unit=r["unit"],
                price_min=int(r["price_min_inr_per_month"]), price_max=int(r["price_max_inr_per_month"]),
                setup=int(r["one_time_setup_inr"]), min_contract=int(r["min_contract_months"]),
                tiers=[int(t) for t in r["available_city_tiers"].split(";") if t],
                min_employees=int(r["min_employees"]), min_sites=int(r["min_sites"]),
                requires_gstin=r["requires_gstin"].strip().upper() == "Y",
                requires_one_of=[p for p in r["requires_one_of"].split("|") if p],
                install_days=int(r["typical_install_days"]),
                segments=r["target_segments"].split(";"),
            )
    return out


CATALOGUE = load_catalogue()


@dataclass
class Profile:
    """What the advisor learns about the business. Nothing here is PII."""
    business_type: str = ""
    segment: str = "micro"          # micro | prof | multi | mfg
    employees: int = 1
    sites: int = 1
    city_tier: int = 2
    has_gstin: bool = False
    current_internet: str = "hotspot"   # hotspot | home | business | leased | mixed | none
    needs: List[str] = field(default_factory=list)  # billing, customers, cctv, email, phone, uptime, security, website, backup, iot, fleet
    language: str = "hi"


@dataclass
class LineItem:
    product_id: str
    qty: int
    unit_price: int
    optional: bool = False       # toggle-able add-on
    selected: bool = True
    why: str = ""

    @property
    def product(self) -> Product:
        return CATALOGUE[self.product_id]


def eligibility_errors(pid: str, profile: Profile, bundle_ids: List[str]) -> List[str]:
    """Return the reasons a product cannot be sold to this profile (empty = eligible)."""
    p = CATALOGUE[pid]
    errs = []
    if profile.city_tier not in p.tiers:
        errs.append(f"{p.name} is only sold in tier {', '.join(map(str, p.tiers))} cities")
    if profile.employees < p.min_employees:
        errs.append(f"{p.name} needs at least {p.min_employees} employees")
    if profile.sites < p.min_sites:
        errs.append(f"{p.name} needs at least {p.min_sites} sites")
    if p.requires_gstin and not profile.has_gstin:
        errs.append(f"{p.name} needs an active GSTIN")
    if p.requires_one_of and not any(x in bundle_ids for x in p.requires_one_of):
        names = " or ".join(CATALOGUE[x].name for x in p.requires_one_of)
        errs.append(f"{p.name} needs {names} in the same bundle")
    return errs


def price_in_band(pid: str, price: int) -> bool:
    p = CATALOGUE[pid]
    return p.price_min <= price <= p.price_max


# ---------------------------------------------------------------------------
# Bundle templates. Unit prices are the catalogue minimum (we compete on
# simplicity, not on a discount the owner cannot verify). Every template is
# checked against the rule engine in tests/test_all.py.
# ---------------------------------------------------------------------------

def _li(pid, qty=1, optional=False, selected=True, why=""):
    return LineItem(pid, qty, CATALOGUE[pid].price_min, optional, selected, why)


def recommend(profile: Profile) -> dict:
    """Pick a bundle template for the profile, then filter by eligibility."""
    n = set(profile.needs)
    seg = profile.segment
    items: List[LineItem] = []
    name, term = "", 12

    if "simonly" in n:
        # 280 leads a quarter drop because they "only wanted a mobile plan". Give them exactly that.
        name, term = "Just a SIM", 1
        lines = max(1, min(profile.employees // 3, 5))
        items.append(_li("P07", qty=lines, why=f"{lines} business line{'s' if lines > 1 else ''} with 50 GB and unlimited calls; no contract"))
        items.append(_li("P08", optional=True, selected=False, why="Upgrade a line to 150 GB with roaming and priority care"))
        conn = "P04" if profile.current_internet in ("hotspot", "none") else "P01"
        items.append(_li(conn, optional=True, selected=False, why="If you ever want the shop off your phone's hotspot: broadband from ₹899"))
        items.append(_li("P15", optional=True, selected=False, why="Verified WhatsApp channel with catalogue (needs GSTIN)"))
    elif seg == "micro":
        term = 6 if not profile.has_gstin else 12
        name = "Dukaan Plus" if profile.has_gstin else "Dukaan Start"
        conn = "P04" if profile.current_internet in ("hotspot", "none", "home") else "P01"
        items.append(_li(conn, why="Plug-and-play 5G AirFiber: live in 2 days, no fibre digging" if conn == "P04" else "Fibre 100 Mbps for a shop that already has a fibre line"))
        items.append(_li("P07", why="One business mobile line with 50 GB so the shop's number stops being your personal number"))
        items.append(_li("P22", optional=True, selected="wifi" in n or "customers" in n, why="Separate customer Wi-Fi with content filtering"))
        items.append(_li("P15", optional=True, selected=profile.has_gstin and "customers" in n, why="Verified WhatsApp channel with catalogue; 1,000 conversations a month"))
        items.append(_li("P19", optional=True, selected="billing" in n, why="GST-ready billing, inventory and UPI on a tablet"))
        items.append(_li("P23", qty=2, optional=True, selected="cctv" in n, why="HD cameras with 30-day cloud recording, viewable on your phone"))
        items.append(_li("P18", optional=True, selected="website" in n, why="Domain, 5-page website and SSL"))
    elif seg == "prof":
        name = "Clinic & Office"
        users = max(2, min(profile.employees, 25))
        s = max(profile.sites, 1)
        items.append(_li("P02", qty=s, why="300 Mbps business fibre with optional static IP" + (f", at each of {s} locations" if s > 1 else "")))
        items.append(_li("P09", qty=s, why="4G/5G failover so the clinic never loses billing or appointments"))
        items.append(_li("P16", qty=users, why=f"Business email on your own domain for {users} people, with documents and video meetings"))
        items.append(_li("P20", qty=users, why=f"Antivirus and ransomware protection for {users} devices"))
        items.append(_li("P17", why="Automatic 1 TB backup of PCs and phones"))
        items.append(_li("P08", qty=2, why="Two mobile lines with 150 GB, roaming and priority care"))
        items.append(_li("P12", qty=2, optional=True, selected="phone" in n, why="Cloud phone lines with IVR and call recording"))
        items.append(_li("P11", optional=True, selected="cctv" in n or "phone" in n, why="Fixed public IP for CCTV or remote access"))
        items.append(_li("P23", qty=2, optional=True, selected="cctv" in n, why="HD cameras with 30-day cloud recording"))
        items.append(_li("P13", optional=True, selected="phone" in n, why="1800 toll-free number for patients or clients"))
        items.append(_li("P18", optional=True, selected="website" in n, why="Domain, 5-page website and SSL"))
    elif seg == "multi":
        name = "Multi-site"
        term = 24
        s = max(profile.sites, 2)
        items.append(_li("P02", qty=s, why=f"300 Mbps fibre at each of {s} sites"))
        items.append(_li("P09", qty=s, why="Failover at every site"))
        items.append(_li("P10", qty=s, optional=True, selected="central" in n or "uptime" in n, why="One dashboard for all links, app-priority routing"))
        items.append(_li("P23", qty=2 * s, optional=True, selected="cctv" in n, why="Two cloud cameras per site"))
        items.append(_li("P19", qty=s, optional=True, selected="billing" in n, why="One POS per site, central inventory"))
        items.append(_li("P08", qty=s, why="One manager line per site"))
        items.append(_li("P13", optional=True, selected=True, why="One toll-free number routed to the right outlet"))
        items.append(_li("P15", optional=True, selected="customers" in n, why="WhatsApp channel for orders and offers"))
    else:  # mfg
        name = "Factory Connect (quoted after site survey)"
        term = 12
        items.append(_li("P05", why="Dedicated 20 Mbps leased line with 99.5% SLA"))
        items.append(_li("P21", why="Managed firewall watched by the Accel SOC"))
        items.append(_li("P24", qty=10, optional=True, selected="iot" in n, why="IoT sensors for machine uptime and energy"))
        items.append(_li("P16", qty=10, why="Email and office suite for the office staff"))
        items.append(_li("P08", qty=2, why="Two business lines with 150 GB and roaming for the owner and plant manager"))
        items.append(_li("P25", qty=2, optional=True, selected="fleet" in n, why="GPS trackers on delivery vehicles"))
        items.append(_li("P20", qty=10, optional=True, selected="security" in n, why="Antivirus and ransomware protection for office PCs"))
        items.append(_li("P17", optional=True, selected="email" in n or "security" in n, why="Automatic 1 TB backup"))

    # Rule engine: drop anything ineligible, and explain
    kept, removed = [], []
    selected_ids = [li.product_id for li in items if not li.optional]
    for li in items:
        errs = eligibility_errors(li.product_id, profile, selected_ids)
        if errs:
            removed.append({"product_id": li.product_id, "name": li.product.name, "reasons": errs})
        else:
            kept.append(li)
    return {"bundle_name": name, "contract_months": term, "items": kept, "removed": removed,
            "install_days": max([li.product.install_days for li in kept if li.selected] or [0])}


def price_bundle(items: List[LineItem], selected: Optional[Dict[str, bool]] = None) -> dict:
    monthly = setup = 0
    lines = []
    for li in items:
        sel = li.selected if selected is None else selected.get(li.product_id, li.selected)
        if li.optional and not sel:
            lines.append({"product_id": li.product_id, "name": li.product.name, "qty": li.qty, "unit_price": li.unit_price, "unit": li.product.unit, "optional": True, "selected": False, "why": li.why, "setup": li.product.setup * li.qty})
            continue
        assert price_in_band(li.product_id, li.unit_price), f"{li.product_id} priced outside catalogue band"
        monthly += li.unit_price * li.qty
        setup += li.product.setup * li.qty
        lines.append({"product_id": li.product_id, "name": li.product.name, "qty": li.qty, "unit_price": li.unit_price, "unit": li.product.unit, "optional": li.optional, "selected": True, "why": li.why, "setup": li.product.setup * li.qty})
    return {"monthly": monthly, "setup": setup, "lines": lines}
