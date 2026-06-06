"""Seeded, labeled telco support tickets for the benchmark.

`build_tickets()` returns >=300 tickets, each:
    {id, text, correct_tool, difficulty, escalation_target, is_escalation}

Design rules (matter for validity):
- clear / medium  -> exactly one correct_tool (an ANSWER_TOOL), is_escalation=False.
- ambiguous       -> the right action is to ESCALATE to a named desk;
                     correct_tool=None, is_escalation=True, escalation_target set.
- Phrasing avoids the tool-name keyword so selection is not keyword-trivial,
  and several `medium` templates are deliberate traps that sit near a different
  tool (refund-wording -> check_invoice, not issue_refund; "worried abroad" ->
  check_roaming, not enable_roaming).
- Fully deterministic given config.TICKET_SEED.
"""

from __future__ import annotations

import random
import re

from bench import config
from data.tools import ANSWER_TOOL_NAMES

# --- slot fillers -----------------------------------------------------------
SLOTS: dict[str, list[str]] = {
    "device": ["iPhone 17 Pro", "iPhone 17", "Galaxy S26", "Galaxy S26 Ultra",
               "Pixel 10", "Redmi Note 14", "Galaxy A56", "iPhone 16e"],
    "router": ["5G home router", "4G MiFi", "home broadband router", "5G hub"],
    "pack": ["500-text", "1000-SMS", "unlimited-texts", "250-message"],
    "plan": ["unlimited data", "the 100GB plan", "a cheaper plan", "the family plan",
             "the 50GB tariff", "the SIM-only deal"],
    "month": ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "last month"],
    "amount": ["£12", "£45.50", "€20", "£9.99", "£150", "£30", "£8.40", "£220"],
    "country": ["Spain", "France", "Germany", "the US", "Italy", "Turkey",
                "Thailand", "Portugal", "Greece", "Japan"],
    "operator": ["my old network", "Vodafone", "EE", "O2", "Three", "my previous provider"],
    "ref": ["ORD-22815", "ORD-90413", "case 5512", "ticket 7781", "ref 33027"],
}

# --- answer-tool templates: {tool: {difficulty: [templates]}} ---------------
TOOL_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "order_sms_pack": {
        "clear": [
            "Can you add the {pack} bundle to my line?",
            "I'd like to buy the {pack} add-on for my number.",
            "Please put the {pack} message pack on my account.",
            "Sign me up for the {pack} texting bundle.",
            "Add the {pack} messaging extra to my plan please.",
        ],
        "medium": [
            "I keep running out of texts every single month, can you sort that?",
            "My teenager texts constantly and we're always over the limit — fix it please.",
            "I need a much bigger SMS allowance than whatever I'm on now.",
            "Messages stop sending halfway through the month, I need more headroom.",
        ],
    },
    "run_line_diagnostic": {
        "clear": [
            "No internet at home since this morning.",
            "My line's been completely dead since {month}.",
            "I've had no signal all day, can you check the line?",
            "Mobile data just stopped working a few hours ago.",
            "Nothing's connecting — no calls, no data — since yesterday.",
        ],
        "medium": [
            "Calls keep dropping and pages won't load, something's off with my connection.",
            "Everything worked yesterday, today nothing loads at all. Help?",
            "Web pages time out constantly even on full bars, what's going on?",
        ],
    },
    "check_invoice": {
        "clear": [
            "I was billed twice for {month}.",
            "There's a charge on my bill I don't recognise.",
            "My {month} bill is way higher than usual, what is this?",
            "Why was I charged {amount} this month?",
            "A random {amount} fee showed up on my statement.",
        ],
        "medium": [  # refund-wording traps -> investigate first, not issue_refund
            "Refund a charge for a service I never used.",
            "I want my money back for the {amount} you took wrongly.",
            "You overcharged me, I want a refund of {amount}.",
            "Give me back the {amount} you billed me by mistake.",
        ],
    },
    "issue_refund": {
        "clear": [  # refund already confirmed/approved -> action it
            "You already agreed last week to refund my {amount} double charge, please process it.",
            "The supervisor approved a {amount} credit on {ref}, action the refund now.",
            "Refund was confirmed for {ref} — please push it through.",
            "I was promised {amount} back on {ref}, can you release it today?",
        ],
        "medium": [
            "I returned the device under {ref} and was told I'd get {amount} back, where is it?",
            "Cancellation was accepted and a {amount} refund agreed — it still hasn't landed.",
        ],
    },
    "create_order": {
        "clear": [
            "I'd like to order the {device}.",
            "Can I buy the {device} on my account?",
            "Place an order for a {device} please.",
            "I want to get the new {router}.",
            "Put me down for the {device}, ready to order.",
        ],
        "medium": [
            "My phone's on its last legs, time for a new {device} — set me up.",
            "We need another handset for my partner, the {device} ideally.",
            "Looking to finally get the {router} sorted for the house.",
        ],
    },
    "check_stock": {
        "clear": [
            "Is the {device} in stock right now?",
            "Do you have the {device} available?",
            "Have you got the {device} back in stock yet?",
            "Can I get the {device} today or is it sold out?",
            "Is the {router} available to ship this week?",
        ],
        "medium": [
            "Thinking about the {device} — any point coming in or is there a wait?",
            "Before I decide on the {device}, are they even available?",
        ],
    },
    "activate_sim": {
        "clear": [
            "My replacement SIM still has no signal.",
            "New SIM won't activate at all.",
            "Can you put my new eSIM live please.",
            "Swapped my SIM and it shows no network.",
            "Just got my SIM, it's stuck on 'no service'.",
        ],
        "medium": [
            "Got my new SIM days ago and still can't make calls, what's wrong?",
            "Moved everything to the new SIM but it never came online.",
        ],
    },
    "update_plan": {
        "clear": [
            "Switch me to {plan}.",
            "I want to move to {plan}.",
            "Change my tariff to {plan} please.",
            "Upgrade me to {plan}.",
            "Put me on {plan} from next month.",
        ],
        "medium": [  # confusable with set_data_cap / downgrade
            "I'm always over my data, I think I need a different deal.",
            "I want to pay less each month, change something on my account.",
            "This tariff doesn't suit me anymore, move me to something better.",
        ],
    },
    "check_roaming": {
        "clear": [
            "Data is crawling whenever I travel abroad.",
            "My internet barely works in {country}.",
            "Connection dies the moment I land overseas.",
            "Slow data every single time I'm out of the country.",
            "Can't load anything on my phone while I'm in {country}.",
        ],
        "medium": [  # confusable with enable_roaming
            "I'm off to {country} next week and worried my phone won't work, can you check?",
            "Heading abroad soon — last time data was unusable, make sure it's fine.",
        ],
    },
    "port_number": {
        "clear": [
            "I want to keep my number and move to you from another network.",
            "Port my old number over to your SIM.",
            "Bring my number across from {operator}.",
            "Transfer my existing number to this new account.",
            "Moving to you but I must keep the same mobile number.",
        ],
        "medium": [
            "Leaving {operator} but I have to keep my number, how does that work?",
            "Switching over to you — the number has to come with me though.",
        ],
    },
}

# --- ambiguous templates: {desk: [templates]} (correct action = escalate) ---
DESK_TEMPLATES: dict[str, list[str]] = {
    "Network Ops": [
        "Half my street has had no signal for three days and your app insists everything's fine — sort it out.",
        "Intermittent drops for weeks now, two engineers have been out and it's still broken.",
        "Data works then vanishes for hours at random, no pattern, on every device in the house.",
        "Whole area's been patchy since the storm, this is beyond a quick reset.",
        "Coverage map says I'm fine but I get nothing indoors and nobody can explain why.",
        "Third outage this month in {country}-style dead zones around my postcode, I need a real answer.",
    ],
    "Billing": [
        "I've been overcharged for months, promised credits that never came, and now you're threatening collections — fix this mess.",
        "My bill shows three different totals on three different letters and nobody can explain it.",
        "Years of small mystery charges adding up, I want the whole account reviewed properly.",
        "You've taken {amount} twice, refunded once, charged a fee for your own mistake — I'm lost.",
        "Every month there's a new unexplained line item, this needs someone senior to untangle.",
    ],
    "Retention": [
        "Third time calling. I want to cancel my contract.",
        "I'm leaving unless someone gives me a serious reason to stay.",
        "Done with you after years — cancel everything, though honestly you could try to change my mind.",
        "Competitor's offering half the price, why would I possibly stay with you?",
        "I've had enough of the service and the prices, talk me out of walking or I'm gone.",
    ],
    "Tech Support": [
        "New phone won't hold a connection, the settings all look right, I've tried everything you're about to suggest.",
        "Wi-Fi calling, voicemail and data all broke at once after an update, it's a total mess.",
        "Nothing works properly since I changed handsets and the usual fixes do nothing.",
        "Calls connect but no audio, texts arrive late, data drops — all on a phone that's days old.",
        "I've reset, reseated the SIM, reinstalled everything and it's still completely broken.",
    ],
    "Sales": [
        "We're a 12-person business wanting lines, devices and a proper deal — who do I actually talk to?",
        "Want to switch the whole family over with trade-ins and a custom bundle, I need someone to build it.",
        "Looking at moving five accounts across with new handsets, need a tailored quote.",
        "Setting up a new office and need data SIMs, phones and a contract — point me to the right team.",
        "Big upgrade for the team plus accessories and insurance, this needs a human to price up.",
    ],
}

_SLOT_RE = re.compile(r"\{(\w+)\}")

# Natural politeness wrappers — real customers phrase the same request many
# ways. These multiply each template into many surface variants without making
# the text keyword-trivial for the target tool.
PREFIXES = ["", "Hi, ", "Hello — ", "Quick one: ", "Hey, ", "Morning, ",
            "Sorry to bother you, ", "Right, so ", "OK, ", "Listen, "]
SUFFIXES = ["", " Thanks.", " Cheers.", " Please help.", " Appreciate it.",
            " ASAP please.", " Can you help?", " Thanks in advance."]


def _fill(template: str, rng: random.Random) -> str:
    return _SLOT_RE.sub(lambda m: rng.choice(SLOTS[m.group(1)]), template)


def _decorate(body: str, rng: random.Random) -> str:
    prefix = rng.choice(PREFIXES)
    suffix = rng.choice(SUFFIXES)
    if prefix:  # lowercase the first letter so "Hi, no internet…" reads naturally
        body = body[0].lower() + body[1:]
    return f"{prefix}{body}{suffix}"


def _generate(templates: list[str], count: int, rng: random.Random, tag: str) -> list[str]:
    """Produce `count` unique texts from `templates` via slot + politeness
    variation. Fails loud if it can't yield enough uniques (don't silently
    return fewer)."""
    out: list[str] = []
    seen: set[str] = set()
    attempts = 0
    max_attempts = count * 400
    while len(out) < count and attempts < max_attempts:
        attempts += 1
        text = _decorate(_fill(templates[len(out) % len(templates)], rng), rng)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    assert len(out) == count, (
        f"{tag}: could only generate {len(out)}/{count} unique tickets; "
        f"add more templates or slot variety."
    )
    return out


def _allocate(total: int, buckets: int) -> list[int]:
    """Split `total` as evenly as possible across `buckets`."""
    base, extra = divmod(total, buckets)
    return [base + (1 if i < extra else 0) for i in range(buckets)]


def build_tickets() -> list[dict]:
    rng = random.Random(config.TICKET_SEED)

    n_clear = round(config.N_TICKETS * config.DIFFICULTY_MIX["clear"])
    n_medium = round(config.N_TICKETS * config.DIFFICULTY_MIX["medium"])
    n_ambiguous = config.N_TICKETS - n_clear - n_medium  # remainder, keeps sum exact

    tools = sorted(TOOL_TEMPLATES.keys())
    assert set(tools) == ANSWER_TOOL_NAMES, "ticket tools must match the answer set"
    desks = config.ESCALATION_DESKS

    rows: list[dict] = []

    # clear + medium, allocated across the 10 answer tools
    for difficulty, total in (("clear", n_clear), ("medium", n_medium)):
        alloc = _allocate(total, len(tools))
        for tool, cnt in zip(tools, alloc):
            texts = _generate(TOOL_TEMPLATES[tool][difficulty], cnt, rng,
                              tag=f"{tool}/{difficulty}")
            for txt in texts:
                rows.append({
                    "text": txt, "correct_tool": tool, "difficulty": difficulty,
                    "escalation_target": None, "is_escalation": False,
                })

    # ambiguous, allocated across the 5 desks
    alloc = _allocate(n_ambiguous, len(desks))
    for desk, cnt in zip(desks, alloc):
        texts = _generate(DESK_TEMPLATES[desk], cnt, rng, tag=f"{desk}/ambiguous")
        for txt in texts:
            rows.append({
                "text": txt, "correct_tool": None, "difficulty": "ambiguous",
                "escalation_target": desk, "is_escalation": True,
            })

    # assign stable, unique 4-digit ids from a seeded shuffle (independent of order)
    rng.shuffle(rows)
    id_pool = list(range(1000, 1000 + len(rows) * 3))
    rng.shuffle(id_pool)
    for row, num in zip(rows, id_pool[: len(rows)]):
        row["id"] = f"TK-{num}"

    _validate(rows, n_clear, n_medium, n_ambiguous)
    return rows


def _validate(rows: list[dict], n_clear: int, n_medium: int, n_ambiguous: int) -> None:
    assert len(rows) == config.N_TICKETS, f"{len(rows)} != {config.N_TICKETS}"
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate ticket ids"
    texts = [r["text"] for r in rows]
    assert len(set(texts)) == len(texts), "duplicate ticket texts"
    by_diff: dict[str, int] = {}
    for r in rows:
        by_diff[r["difficulty"]] = by_diff.get(r["difficulty"], 0) + 1
        if r["difficulty"] == "ambiguous":
            assert r["is_escalation"] and r["correct_tool"] is None
            assert r["escalation_target"] in config.ESCALATION_DESKS
        else:
            assert not r["is_escalation"] and r["escalation_target"] is None
            assert r["correct_tool"] in ANSWER_TOOL_NAMES
    assert by_diff == {"clear": n_clear, "medium": n_medium, "ambiguous": n_ambiguous}, by_diff


if __name__ == "__main__":
    rows = build_tickets()
    from collections import Counter
    print("total:", len(rows))
    print("by difficulty:", dict(Counter(r["difficulty"] for r in rows)))
    print("by tool:", dict(Counter(r["correct_tool"] for r in rows if r["correct_tool"])))
    print("by desk:", dict(Counter(r["escalation_target"] for r in rows if r["escalation_target"])))
    for r in rows[:6]:
        print(" ", r["id"], "|", r["difficulty"], "|", r["correct_tool"] or r["escalation_target"], "|", r["text"][:60])
