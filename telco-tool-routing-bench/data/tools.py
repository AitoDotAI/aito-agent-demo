"""Scalable tool catalog for the telco tool-routing benchmark.

`build_tools(n)` returns a list of `n` tools, each:
    {"name", "signature", "description", "domain"}

Invariant that keeps the benchmark valid
-----------------------------------------
The sweep's smallest catalog is 12 tools (config.TOOL_COUNTS), and the SAME
labeled tickets are resolved at every catalog size. So every ticket's
`correct_tool` must be present at *every* N — otherwise a baseline would be
structurally unable to pick the right tool at small N, which is not the effect
we are measuring. We therefore cap the distinct "answer" tools at 10
(ANSWER_TOOLS). These are always included; raising N only adds realistic
*distractors* ("hay"), which is exactly the difficulty the LLM baselines face
and that Aito never sees (Aito predicts over historical tool labels, not the
catalog).

`build_tools(n)` = ANSWER_TOOLS (10) + first (n-10) distractors, then a
deterministic shuffle (seeded, independent of n) so the answer tools are not
always at the front of an LLM prompt.
"""

from __future__ import annotations

import random

from bench import config

# --- the 10 answer tools (every ticket's correct_tool is one of these) ------
# domain ∈ {billing, network, provisioning, sales, devices}
ANSWER_TOOLS: list[dict] = [
    {"name": "order_sms_pack", "signature": "order_sms_pack(msisdn, pack_size)",
     "description": "Add a prepaid SMS bundle (e.g. 500 texts) to a subscriber line.",
     "domain": "billing"},
    {"name": "run_line_diagnostic", "signature": "run_line_diagnostic(msisdn)",
     "description": "Run remote connectivity diagnostics on a line that has no service or degraded data/voice.",
     "domain": "network"},
    {"name": "check_invoice", "signature": "check_invoice(account_id, period)",
     "description": "Pull up a billing statement to investigate a disputed, duplicate or unexpected charge before any refund.",
     "domain": "billing"},
    {"name": "issue_refund", "signature": "issue_refund(account_id, charge_id, amount)",
     "description": "Issue a confirmed monetary refund for a charge already established as incorrect.",
     "domain": "billing"},
    {"name": "create_order", "signature": "create_order(account_id, sku)",
     "description": "Place an order for a new device, router or hardware product from the catalog.",
     "domain": "sales"},
    {"name": "check_stock", "signature": "check_stock(sku)",
     "description": "Check current inventory and availability of a device or accessory.",
     "domain": "devices"},
    {"name": "activate_sim", "signature": "activate_sim(msisdn, iccid)",
     "description": "Activate or re-provision a SIM/eSIM that is not yet registering on the network.",
     "domain": "provisioning"},
    {"name": "update_plan", "signature": "update_plan(account_id, plan_code)",
     "description": "Change a subscriber's tariff/plan (e.g. move to unlimited data).",
     "domain": "sales"},
    {"name": "check_roaming", "signature": "check_roaming(msisdn, country)",
     "description": "Check and troubleshoot roaming status and data behaviour while the subscriber is in another country.",
     "domain": "network"},
    {"name": "port_number", "signature": "port_number(msisdn, donor_operator)",
     "description": "Port a phone number in from, or out to, another operator.",
     "domain": "provisioning"},
]
ANSWER_TOOL_NAMES = {t["name"] for t in ANSWER_TOOLS}

# --- hand-written distractors (realistic, near-neighbour, NOT obvious filler) -
# These are the tools a real MVNO support stack would have. Several deliberately
# sit close to an answer tool (reset_modem near run_line_diagnostic; dispute_charge
# near check_invoice; enable_roaming near check_roaming) to make selection hard.
HANDWRITTEN_DISTRACTORS: list[dict] = [
    {"name": "reset_modem", "signature": "reset_modem(device_id)", "domain": "network",
     "description": "Remotely power-cycle a home broadband modem/router."},
    {"name": "schedule_technician", "signature": "schedule_technician(account_id, window)", "domain": "network",
     "description": "Book an on-site field engineer visit for a fault that cannot be fixed remotely."},
    {"name": "check_coverage", "signature": "check_coverage(postcode)", "domain": "network",
     "description": "Look up expected network coverage and signal strength for an address."},
    {"name": "check_network_outage", "signature": "check_network_outage(region)", "domain": "network",
     "description": "Check for known mast/cell outages affecting an area."},
    {"name": "dispute_charge", "signature": "dispute_charge(account_id, charge_id)", "domain": "billing",
     "description": "Open a formal billing dispute case once a charge is contested."},
    {"name": "enable_roaming", "signature": "enable_roaming(msisdn)", "domain": "provisioning",
     "description": "Switch on the roaming permission flag on an account before travel."},
    {"name": "close_account", "signature": "close_account(account_id)", "domain": "retention",
     "description": "Permanently terminate a customer's account and services."},
    {"name": "apply_retention_offer", "signature": "apply_retention_offer(account_id, offer_code)", "domain": "retention",
     "description": "Apply a discount or loyalty offer to retain a customer who wants to leave."},
    {"name": "reset_voicemail_pin", "signature": "reset_voicemail_pin(msisdn)", "domain": "devices",
     "description": "Reset the voicemail access PIN for a subscriber."},
    {"name": "block_sim", "signature": "block_sim(msisdn)", "domain": "provisioning",
     "description": "Suspend/blacklist a SIM after a lost or stolen device report."},
    {"name": "order_esim", "signature": "order_esim(account_id)", "domain": "provisioning",
     "description": "Issue a new eSIM profile QR code to a subscriber."},
    {"name": "check_data_usage", "signature": "check_data_usage(msisdn, period)", "domain": "billing",
     "description": "Report how much mobile data a line has consumed in a period."},
    {"name": "set_data_cap", "signature": "set_data_cap(msisdn, cap_gb)", "domain": "billing",
     "description": "Set or change a monthly data spending cap on a line."},
    {"name": "top_up_balance", "signature": "top_up_balance(msisdn, amount)", "domain": "billing",
     "description": "Add prepaid credit/balance to a pay-as-you-go line."},
    {"name": "update_billing_address", "signature": "update_billing_address(account_id, address)", "domain": "billing",
     "description": "Update the postal/billing address on an account."},
    {"name": "setup_autopay", "signature": "setup_autopay(account_id, method)", "domain": "billing",
     "description": "Enrol an account in automatic recurring payment."},
    {"name": "unlock_device", "signature": "unlock_device(imei)", "domain": "devices",
     "description": "Network-unlock a handset so it accepts other operators' SIMs."},
    {"name": "configure_apn", "signature": "configure_apn(msisdn)", "domain": "devices",
     "description": "Push correct mobile data APN settings to a handset."},
    {"name": "enable_call_forwarding", "signature": "enable_call_forwarding(msisdn, target)", "domain": "devices",
     "description": "Set up call forwarding/divert to another number."},
    {"name": "configure_voicemail_greeting", "signature": "configure_voicemail_greeting(msisdn)", "domain": "devices",
     "description": "Change a subscriber's voicemail greeting message."},
    {"name": "register_complaint", "signature": "register_complaint(account_id, text)", "domain": "retention",
     "description": "Log a formal customer complaint for case tracking."},
    {"name": "schedule_callback", "signature": "schedule_callback(account_id, when)", "domain": "retention",
     "description": "Book a callback from an agent at a requested time."},
    {"name": "check_loyalty_points", "signature": "check_loyalty_points(account_id)", "domain": "sales",
     "description": "Look up a customer's reward/loyalty point balance."},
    {"name": "order_accessory", "signature": "order_accessory(account_id, sku)", "domain": "sales",
     "description": "Order a phone case, charger or other accessory."},
    {"name": "check_upgrade_eligibility", "signature": "check_upgrade_eligibility(account_id)", "domain": "sales",
     "description": "Check whether a customer is eligible for a handset upgrade."},
    {"name": "transfer_ownership", "signature": "transfer_ownership(account_id, new_holder)", "domain": "provisioning",
     "description": "Transfer account/line ownership to a different person."},
    {"name": "check_contract_status", "signature": "check_contract_status(account_id)", "domain": "retention",
     "description": "Show remaining contract term, end date and early-termination fee."},
    {"name": "update_marketing_consent", "signature": "update_marketing_consent(account_id, opt_in)", "domain": "retention",
     "description": "Change a customer's marketing/communication preferences."},
    {"name": "verify_identity", "signature": "verify_identity(account_id, doc)", "domain": "provisioning",
     "description": "Run an identity/KYC verification check on an account holder."},
    {"name": "check_number_availability", "signature": "check_number_availability(prefix)", "domain": "sales",
     "description": "Check whether a desired phone number/golden number is free."},
    {"name": "provision_static_ip", "signature": "provision_static_ip(account_id)", "domain": "network",
     "description": "Assign a static IP to a business broadband line."},
    {"name": "reset_router_wifi", "signature": "reset_router_wifi(device_id)", "domain": "network",
     "description": "Reset the Wi-Fi SSID/password on a home router."},
]

# domain templates used to pad beyond the hand-written set with realistic names
_VERBS = ["check", "update", "reset", "configure", "enable", "disable", "schedule",
          "order", "cancel", "verify", "register", "review", "renew", "suspend"]
_OBJECTS = {
    "billing": ["paper_billing", "billing_cycle", "tax_invoice", "credit_note", "direct_debit",
                "spending_limit", "itemised_bill", "vat_receipt", "payment_plan", "late_fee"],
    "network": ["signal_booster", "cell_priority", "qos_profile", "ipv6_setting", "dns_setting",
                "femtocell", "throttle_policy", "bandwidth_profile", "latency_test", "mast_ticket"],
    "provisioning": ["multisim", "data_only_sim", "puk_code", "imei_swap", "number_reservation",
                     "service_bundle", "line_rental", "secondary_line", "sim_swap", "msisdn_change"],
    "sales": ["trade_in", "insurance_addon", "device_quote", "bundle_offer", "referral_code",
              "student_discount", "family_plan", "gift_card", "promo_voucher", "addon_catalog"],
    "devices": ["screen_protector", "wearable_pairing", "esim_transfer", "device_backup",
                "parental_control", "wifi_calling", "hotspot_setting", "ringtone", "nfc_payment", "vpn_profile"],
    "retention": ["winback_offer", "pause_subscription", "downgrade_plan", "feedback_survey",
                  "complaint_status", "goodwill_credit", "loyalty_tier", "exit_survey", "hold_account"],
}


def _generated_distractors() -> list[dict]:
    """Templated but realistic tools to pad the catalog beyond the hand-written
    set. Deterministic, deduped against answer + hand-written names."""
    taken = ANSWER_TOOL_NAMES | {t["name"] for t in HANDWRITTEN_DISTRACTORS}
    out: list[dict] = []
    for domain, objects in _OBJECTS.items():
        for obj in objects:
            for verb in _VERBS:
                name = f"{verb}_{obj}"
                if name in taken:
                    continue
                taken.add(name)
                pretty = obj.replace("_", " ")
                out.append({
                    "name": name,
                    "signature": f"{name}(account_id)",
                    "description": f"{verb.capitalize()} the {pretty} for a subscriber account.",
                    "domain": domain,
                })
    return out


_DISTRACTOR_POOL = HANDWRITTEN_DISTRACTORS + _generated_distractors()
_MAX_N = len(ANSWER_TOOLS) + len(_DISTRACTOR_POOL)


def build_tools(n: int) -> list[dict]:
    """Return exactly `n` tools: the 10 answer tools plus (n-10) distractors,
    deterministically shuffled. Raises if n is outside the supported range."""
    assert n >= len(ANSWER_TOOLS), (
        f"n={n} < {len(ANSWER_TOOLS)} answer tools; every correct_tool must be "
        f"present at every catalog size (see module docstring)."
    )
    assert n <= _MAX_N, f"n={n} exceeds available pool {_MAX_N}; add more distractors."
    tools = list(ANSWER_TOOLS) + _DISTRACTOR_POOL[: n - len(ANSWER_TOOLS)]
    # shuffle keyed on a fixed seed (NOT on n) so ordering is stable and the
    # answer tools are not positionally privileged in an LLM prompt.
    rng = random.Random(config.TOOLS_SEED)
    rng.shuffle(tools)
    # sanity: all answer tools survived
    names = {t["name"] for t in tools}
    assert ANSWER_TOOL_NAMES <= names, "answer tool dropped from catalog"
    assert len(tools) == n
    return tools


if __name__ == "__main__":
    for n in config.TOOL_COUNTS:
        ts = build_tools(n)
        doms = sorted({t["domain"] for t in ts})
        print(f"n={n:>3}: {len(ts)} tools, domains={doms}, "
              f"answers_present={len(ANSWER_TOOL_NAMES & {t['name'] for t in ts})}/10")
    print(f"max catalog supported: {_MAX_N}")
