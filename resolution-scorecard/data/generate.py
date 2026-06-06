"""Generate the resolution dataset: one ticket -> {intent, the one parameter that
intent needs}. Phrasing uses aliases (not the canonical token) so prediction is
real inference, not keyword lookup.

    python -m data.generate
"""

from __future__ import annotations

import json
import random

from bench import config

CUSTOMERS = ["acme", "globex", "initech", "umbrella", "soylent", "hooli", "vehement", "stark"]
DOMAINS = {c: f"{c}.com" for c in CUSTOMERS}
FREEMAIL = ["gmail.com", "outlook.com"]
SOURCES = ["email", "portal", "automation"]

SERVICE_ALIASES = {
    "broadband": ["broadband", "home internet", "fibre line", "wifi connection"],
    "mobile_plan": ["mobile plan", "phone plan", "mobile subscription", "cell plan"],
    "tv_package": ["TV package", "cable TV", "television subscription", "TV plan"],
    "landline": ["landline", "home phone", "fixed line"],
    "roaming_addon": ["roaming add-on", "roaming package", "travel data pack"],
    "cloud_storage": ["cloud storage", "online backup", "cloud drive"],
}
KB_SYMPTOMS = {
    "cracked_screen": ["my screen is cracked", "the glass is shattered", "screen has a big crack", "display glass is broken"],
    "battery_drain": ["battery dies within an hour", "phone won't hold a charge", "the battery drains incredibly fast"],
    "water_damage": ["I dropped my phone in water", "there's liquid damage", "phone got wet and acts strange"],
    "wont_charge": ["my phone won't charge", "the charging port seems dead", "it doesn't charge when plugged in"],
    "no_signal": ["my handset shows no signal at all", "the phone can't get any reception", "no bars on the device anywhere"],
    "software_update": ["it's stuck on the update screen", "the software update failed", "phone won't boot after the update"],
}

INTENT_TEMPLATES = {
    "cancel_service": ["Please cancel my {svc}.", "I want to stop my {svc} subscription.",
                       "Cancel the {svc} on my account.", "I'd like to terminate my {svc}.",
                       "End my {svc} please, I don't need it."],
    "refund": ["I want a refund for my {svc} charge.", "The {svc} bill is wrong, refund it.",
               "I was overcharged on my {svc}, I want my money back.",
               "Please refund the latest {svc} payment.", "Give me a refund for the {svc} fee."],
    "check_outage": ["Is there an outage in {city}?", "No network in {city} since this morning.",
                     "Is the service down around {city}?", "We've got connectivity problems in {city} today.",
                     "Everything's offline here in {city}, is it you?"],
    "find_shop": ["Where's your nearest shop in {city}?", "What are the store hours in {city}?",
                  "Do you have a shop in {city}?", "I need to visit a store in {city}.",
                  "Is there a branch in {city} I can go to?"],
    "repair_help": ["{symptom} — what can I do?", "{symptom}.", "Help, {symptom}.",
                    "{symptom}, can you advise?"],
    "check_balance": ["What's my current balance?", "How much credit do I have left?",
                      "Can you tell me my account balance?", "Check my remaining balance please.",
                      "What's left on my account?"],
}

PREFIXES = ["", "Hi, ", "Hello — ", "Urgent: ", "Hey, ", "Quick one: "]
SUFFIXES = ["", " Thanks.", " Please advise.", " Cheers.", " ASAP."]


def _decorate(body: str, rng: random.Random) -> str:
    p, s = rng.choice(PREFIXES), rng.choice(SUFFIXES)
    if p:
        body = body[0].lower() + body[1:]
    return f"{p}{body}{s}"


def _make(intent: str, rng: random.Random) -> dict:
    row = {"intent": intent, "target_service": None, "location": None, "kb_article": None}
    tmpl = rng.choice(INTENT_TEMPLATES[intent])
    if intent in ("cancel_service", "refund"):
        svc = rng.choice(config.SERVICES)
        row["target_service"] = svc
        text = tmpl.format(svc=rng.choice(SERVICE_ALIASES[svc]))
    elif intent in ("check_outage", "find_shop"):
        city = rng.choice(config.CITIES)
        row["location"] = city
        text = tmpl.format(city=city)
    elif intent == "repair_help":
        kb = rng.choice(config.KB_ARTICLES)
        row["kb_article"] = kb
        text = tmpl.format(symptom=rng.choice(KB_SYMPTOMS[kb]))
    else:
        text = tmpl
    row["text"] = _decorate(text, rng)
    return row


def build(n: int, rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(100000, 100000 + n * 4), n)
    for i in range(n):
        intent = config.INTENTS[i % len(config.INTENTS)]  # balanced
        r = _make(intent, rng)
        cust = rng.choice(CUSTOMERS)
        source = rng.choices(SOURCES, weights=[0.5, 0.3, 0.2])[0]
        if source == "email":
            domain = rng.choices([DOMAINS[cust], rng.choice(FREEMAIL)], weights=[0.7, 0.3])[0]
        else:
            domain = "tickets.helpdesk.io" if source == "portal" else "alerts.monitoring.io"
        r.update({"id": f"RS-{ids[i]}", "customer": cust, "source": source, "sender_domain": domain})
        rows.append(r)
    rng.shuffle(rows)
    return rows


def main() -> None:
    rng = random.Random(config.SEED)
    total = config.TRAIN_SIZE + config.TEST_SIZE
    rows = build(total, rng)
    train, test = rows[: config.TRAIN_SIZE], rows[config.TRAIN_SIZE:]
    assert {r["id"] for r in train}.isdisjoint({r["id"] for r in test})
    (config.DATA_DIR / "train.json").write_text(json.dumps(train, ensure_ascii=False))
    (config.DATA_DIR / "test.json").write_text(json.dumps(test, ensure_ascii=False))
    from collections import Counter
    print(f"train={len(train)} test={len(test)}")
    print("test intents:", dict(Counter(r["intent"] for r in test)))
    for r in test[:6]:
        param = r["target_service"] or r["location"] or r["kb_article"] or "—"
        print(f"  [{r['intent']:>14}] {param:>14} | {r['text'][:60]}")


if __name__ == "__main__":
    main()
