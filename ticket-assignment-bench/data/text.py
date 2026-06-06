"""Customer-agnostic symptom text per product area.

Text reveals the product area (so the area is inferable from text) but NEVER the
customer or project. That is what makes the same symptom recur across customers
and makes text-nearest-neighbour assignment structurally wrong.
"""

from __future__ import annotations

import random
import re

AREA_TEMPLATES: dict[str, list[str]] = {
    "network": [
        "The VPN keeps dropping every few minutes.",
        "I can't reach the internal portal from the office.",
        "Site-to-site tunnel has been down since this morning.",
        "Wifi in the building is painfully slow today.",
        "Latency to the shared drive is through the roof.",
        "DNS resolution fails for internal hostnames.",
        "The firewall is blocking a port we need open.",
        "Remote desktop disconnects constantly over the link.",
        "Our static IP stopped routing overnight.",
        "Packet loss on the main uplink is breaking calls.",
    ],
    "billing": [
        "This month's invoice is almost double the usual amount.",
        "We were charged twice for the same subscription.",
        "There's a line item on the bill nobody recognises.",
        "A payment failed but the money still left the account.",
        "We need a refund for a service we cancelled.",
        "The proration on the upgrade looks wrong.",
        "Tax is being applied at the wrong rate on invoices.",
        "Our annual plan renewed when it should have been monthly.",
        "A credit we were promised never showed up.",
        "The PO number is missing from the latest statement.",
    ],
    "identity": [
        "Nobody on the team can log in this morning.",
        "Single sign-on stopped working after the weekend.",
        "A password reset email never arrives.",
        "MFA prompts are looping and won't accept the code.",
        "An account got locked out after too many attempts.",
        "New starters can't be provisioned into the directory.",
        "SAML assertion is being rejected by the app.",
        "Permissions for a shared mailbox vanished.",
        "The SSO certificate looks like it expired.",
        "A user has the wrong role and can see too much.",
    ],
    "hardware": [
        "My laptop won't boot past the logo screen.",
        "The office printer refuses to come online.",
        "A monitor flickers and then goes black.",
        "We need a replacement device for a broken one.",
        "The docking station stopped charging laptops.",
        "A hard drive is throwing SMART errors.",
        "The conference room screen won't detect input.",
        "A batch of keyboards arrived dead on arrival.",
        "The server fans are running loud and hot.",
        "An RMA needs raising for a faulty unit.",
    ],
    "software": [
        "The desktop app crashes on launch since the update.",
        "A licence key is being rejected as invalid.",
        "The installer fails halfway with an error.",
        "A recent update broke a feature we rely on.",
        "Reports export as empty files now.",
        "The plugin is incompatible with the new version.",
        "Auto-save stopped working in the editor.",
        "The app hangs whenever we open a large file.",
        "A shortcut we configured no longer does anything.",
        "Sync between devices silently stopped.",
    ],
    "cloud": [
        "A production instance is unreachable right now.",
        "Object storage is reporting it is full.",
        "The latest deployment failed and rolled back.",
        "Autoscaling isn't adding nodes under load.",
        "Last night's backup job did not complete.",
        "A managed database is refusing new connections.",
        "The load balancer is returning 502s intermittently.",
        "Container builds are timing out in the pipeline.",
        "A secret rotation broke service authentication.",
        "Egress costs spiked with no change on our side.",
    ],
}

PREFIXES = ["", "Hi, ", "Hello — ", "Urgent: ", "Quick one: ", "Hey, ", "FYI ", "Please help — "]
SUFFIXES = ["", " Thanks.", " Please advise.", " This is blocking us.", " Any update?",
            " Needs sorting today.", " Cheers."]

_SLOT_RE = re.compile(r"\{(\w+)\}")


def make_text(area: str, rng: random.Random) -> str:
    body = rng.choice(AREA_TEMPLATES[area])
    prefix = rng.choice(PREFIXES)
    suffix = rng.choice(SUFFIXES)
    if prefix:
        body = body[0].lower() + body[1:]
    return f"{prefix}{body}{suffix}"


def inject_customer(text: str, alias: str, where: str) -> str:
    """Leak the customer name into the text the way real tickets do — a subject
    prefix or an inline body mention. The name is present but DILUTED among the
    symptom tokens, which is why generic embedding similarity still smears across
    customers."""
    if where == "prefix":          # subject-line / signature style
        return f"[{alias}] {text}"
    if where == "body":            # buried mid/append mention
        return f"{text} (raised on behalf of {alias})"
    return text                    # no mention (e.g. automation-sourced)
