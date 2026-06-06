# Aito: match the answer, not just the question

DB `https://shared.aito.ai/db/aito-agent-demo` · table `resolutions` (question = `text`, answer = `kb_article`)


## My phone screen is shattered.

- **direct answer** (`_match kb_article`): **cracked_screen** (p=0.972)
- retrieved neighbours (`_similarity`):
    · “Hey, the glass is shattered — what can I do? ASAP.” → cracked_screen
    · “Hello — the glass is shattered. Please advise.” → cracked_screen


## The battery dies within an hour.

- **direct answer** (`_match kb_article`): **battery_drain** (p=0.967)
- retrieved neighbours (`_similarity`):
    · “Urgent: battery dies within an hour, can you advise? Thanks.” → battery_drain
    · “Hello — help, battery dies within an hour. Please advise.” → battery_drain


## I dropped my handset in water.

- **direct answer** (`_match kb_article`): **no_signal** (p=0.562)  ✗ expected water_damage
- retrieved neighbours (`_similarity`):
    · “I dropped my phone in water — what can I do? Please advise.” → water_damage
    · “Quick one: i dropped my phone in water — what can I do? Please advise.” → water_damage


## It won't charge when plugged in.

- **direct answer** (`_match kb_article`): **wont_charge** (p=0.986)
- retrieved neighbours (`_similarity`):
    · “Hi, it doesn't charge when plugged in — what can I do? ASAP.” → wont_charge
    · “Hello — it doesn't charge when plugged in. Thanks.” → wont_charge


## No signal at all on the device.

- **direct answer** (`_match kb_article`): **no_signal** (p=1.000)
- retrieved neighbours (`_similarity`):
    · “Quick one: my handset shows no signal at all — what can I do?” → no_signal
    · “Quick one: help, my handset shows no signal at all. ASAP.” → no_signal


## Summary

- direct-answer accuracy (`_match`): 4/5
ok
