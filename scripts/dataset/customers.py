"""Simulated Lumora customer base (fictional people, @example.com e-mail addresses)."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .common import CONTACT_METHODS, CUSTOMER_TYPE_WEIGHTS, sub_rng, weighted_choice

FIRST_NAMES: tuple[str, ...] = (
    "Amara", "Bilal", "Chloe", "Dmitri", "Elena", "Farah", "Gavin", "Hana", "Idris", "Jasmine", "Kofi", "Leila",
    "Marcus", "Nadia", "Oscar", "Priya", "Quentin", "Rosa", "Samir", "Tessa", "Umar", "Valeria", "Wesley", "Ximena",
    "Yusuf", "Zara", "Adrian", "Beatrice", "Callum", "Daria", "Emeka", "Fiona", "Gabriel", "Helena", "Ivan",
    "Juliet", "Kenji", "Lucia", "Mateo", "Noor", "Olivia", "Pavel", "Rania", "Stefan", "Talia", "Uriel", "Vivian",
    "Wanjiru", "Yara", "Zoltan", "Aisha", "Bruno", "Camila", "Declan", "Esme", "Felix", "Greta", "Hamza", "Ingrid",
    "Jonah", "Keira", "Liam", "Mei", "Nikolai", "Odette", "Rafael", "Selin", "Tobias", "Una", "Viktor", "Willa",
    "Ayesha", "Benedict", "Cora", "Dario", "Elif", "Florian", "Giulia", "Hugo", "Imani", "Jarrah", "Kasia", "Lorenzo",
    "Maya", "Nico", "Orla", "Pierre", "Ruth", "Sanjay", "Thea", "Vera", "Wren", "Anika", "Caleb", "Delphine",
    "Ezra", "Freya", "Gideon", "Harriet", "Isla", "Joaquin", "Kamila", "Leon", "Mirela", "Nathan", "Ophelia",
    "Ronan", "Sofia", "Theo", "Ursula", "Magnus", "Nell", "Aurelio", "Bianca", "Cyrus", "Dalia", "Eamon",
)
LAST_NAMES: tuple[str, ...] = (
    "Okafor", "Lindqvist", "Moreau", "Petrov", "Haddad", "Castillo", "Nakamura", "Brennan", "Adeyemi", "Kowalski",
    "Fitzgerald", "Rahman", "Silva", "Vasquez", "Thornton", "Iqbal", "Novak", "Delacroix", "Mensah", "Albrecht",
    "Sato", "Quinlan", "Rossi", "Oyelaran", "Horvath", "Marchetti", "Jansen", "Khoury", "Whitfield", "Dimitriou",
    "Andersson", "Chowdhury", "Ferreira", "Galloway", "Hartmann", "Ibarra", "Jovanovic", "Kaplan", "Laurent",
    "McAllister", "Nwosu", "Ortega", "Pellegrini", "Rasmussen", "Sokolov", "Tanaka", "Ulrich", "Varga", "Winslow",
    "Yilmaz", "Zielinski", "Ashworth", "Bergstrom", "Cardenas", "Donnelly", "Esposito", "Farouk", "Gunawardena",
    "Holloway", "Ivanova", "Jaramillo", "Kinsella", "Lombardi", "Mbeki", "Nieminen", "Osei", "Pacheco", "Quintero",
    "Rourke", "Sandoval", "Trevisan", "Underwood", "Valdez", "Wojcik", "Xu", "Yamamoto", "Zamora", "Abernathy",
    "Blackwood", "Castellano", "Duarte", "Eriksen", "Fontaine", "Garrido", "Hayashi", "Ingram", "Kuznetsov",
)
CITIES: tuple[str, ...] = (
    "Harrowmere", "Fenwick Ridge", "Larkspur Bay", "Oakhaven", "Wrenfield", "Thistledown", "Marrowby",
    "Quillon Heights", "Selbourne Cove", "Tamsworth", "Elderglen", "Rookhollow", "Brindlemoor", "Calderstone",
    "Ashcombe Vale", "Mistral Point", "Northwick Falls", "Pellham Crossing", "Ravensmere", "Stonebridge Mills",
    "Wexbury", "Yarrowdale", "Juniper Flats", "Kestrel Bay", "Lindenfall", "Moorcroft", "Ottermouth",
    "Pinecrest Harbor", "Quarrington", "Saltmarsh End", "Tidewater Glen", "Umberleigh Park", "Velmont",
    "Willowmere", "Amberlyn", "Birchmont", "Coldharbour Rise", "Dovecote Hill", "Emberton", "Glenwhistle",
)
COMPANIES: tuple[str, ...] = (
    "Harbor Lane Rentals", "Brightside Dental Studio", "Keel & Compass Cafe", "Northgate Property Group",
    "Willow Creek B&B", "Pinnacle Fitness Studio", "Maple & Main Bakery", "Cobalt Coworking",
    "Silverleaf Vacation Homes", "Orchard Row Apartments", "Juniper Physio Clinic", "Redwood Realty",
    "Tidewater Guesthouse", "Lantern Street Books", "Alder Grove Offices", "Summit Ridge Holiday Lets",
    "Copperpot Kitchen", "Blue Heron Motel", "Evergreen Accounting", "Fernhill Veterinary", "Driftwood Surf School",
    "Granite Peak Storage", "Heronsgate Studios", "Ironbark Joinery", "Kingfisher Florists", "Loom & Thread Tailors",
    "Meadowlark Yoga", "Nightjar Records", "Oakline Architects", "Parkside Serviced Flats",
)


def build_customers(seed: int, count: int = 300) -> list[dict[str, Any]]:
    """Build ``count`` customers CUST-10001.. with an exact 60/20/10/10 customer-type split."""
    rng = sub_rng(seed, "customers")
    n_care, n_bus, n_vip = round(count * 0.2), round(count * 0.1), round(count * 0.1)
    types = (["care_plus"] * n_care + ["business"] * n_bus + ["vip"] * n_vip)
    types += ["individual"] * (count - len(types))
    rng.shuffle(types)
    used_names: set[tuple[str, str]] = set()
    used_emails: set[str] = set()
    companies = list(COMPANIES)
    rng.shuffle(companies)
    customers: list[dict[str, Any]] = []
    for idx in range(count):
        while True:
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            if (first, last) not in used_names:
                used_names.add((first, last))
                break
        base = f"{first}.{last}".lower()
        email = f"{base}@example.com"
        n = 2
        while email in used_emails:
            email = f"{base}{n}@example.com"
            n += 1
        used_emails.add(email)
        ctype = types[idx]
        joined = date(2021, 1, 1) + timedelta(days=rng.randint(0, 1900))
        customer: dict[str, Any] = {
            "customer_ref": f"CUST-{10001 + idx}",
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "email": email,
            "city": rng.choice(CITIES),
            "customer_type": ctype,
            "company": companies.pop() if ctype == "business" and companies else None,
            "preferred_contact_method": rng.choice(CONTACT_METHODS),
            "customer_since": joined.isoformat(),
            "care_plus_member": ctype == "care_plus",
        }
        customers.append(customer)
    return customers


class CustomerPool:
    """Deterministic customer assignment that spreads complaints across the customer base.

    A customer is never given two unrelated complaints in the same subcategory, so that
    complaint history ("repeat" / "same issue") is only created deliberately by chains.
    """

    def __init__(self, customers: list[dict[str, Any]]) -> None:
        self.customers = customers
        self.by_ref = {c["customer_ref"]: c for c in customers}
        self.by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in customers:
            self.by_type[c["customer_type"]].append(c)
        self.usage: dict[str, int] = defaultdict(int)
        self.subcategories: dict[str, set[str]] = defaultdict(set)

    def pick(self, rng: random.Random, allowed_types: list[str] | None, subcategory: str | None,
             exclude: set[str] | None = None) -> dict[str, Any]:
        """Pick the least-used customer of a (weighted) allowed type, avoiding subcategory reuse."""
        ctype = weighted_choice(rng, CUSTOMER_TYPE_WEIGHTS, allowed_types or None)
        candidates = [c for c in self.by_type[ctype]
                      if (not subcategory or subcategory not in self.subcategories[c["customer_ref"]])
                      and c["customer_ref"] not in (exclude or set())]
        if not candidates:
            candidates = [c for c in self.by_type[ctype] if c["customer_ref"] not in (exclude or set())]
        lowest = min(self.usage[c["customer_ref"]] for c in candidates)
        tier = [c for c in candidates if self.usage[c["customer_ref"]] == lowest]
        chosen = rng.choice(tier)
        self.usage[chosen["customer_ref"]] += 1
        if subcategory:
            self.subcategories[chosen["customer_ref"]].add(subcategory)
        return chosen

    def other_than(self, rng: random.Random, customer_ref: str) -> dict[str, Any]:
        """A different customer (used for deliberate order-ownership mismatches)."""
        choices = [c for c in self.customers if c["customer_ref"] != customer_ref]
        return rng.choice(choices)
