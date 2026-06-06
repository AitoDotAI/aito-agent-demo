# Resolution scorecard — Aito resolutions


## Seeded dataset slice (TRAIN = 300)

- cancel_service: 50
- refund: 50
- check_outage: 50
- find_shop: 50
- repair_help: 50
- check_balance: 50
ok

## Aito `_predict` on a fixed sample

DB `https://shared.aito.ai/db/aito-agent-demo` · table `resolutions` · predict from {text, sender_domain}

- “Please cancel my broadband.” → intent **cancel_service**, target_service **broadband**
    p(intent)=0.95
- “I want a refund for my mobile plan charge.” → intent **refund**, target_service **broadband**
    p(intent)=0.93
- “Is there an outage in Helsinki?” → intent **check_outage**, location **Helsinki**
    p(intent)=0.94
- “Where is your nearest shop in Tampere?” → intent **find_shop**, location **Helsinki**
    p(intent)=0.78
- “My screen is cracked, the glass is shattered.” → intent **repair_help**, kb_article **cracked_screen**
    p(intent)=0.98
- “What is my account balance?” → intent **check_balance**
    p(intent)=0.98

## Summary

- intent accuracy on sample: 6/6
- parameter accuracy on sample: 3/5
ok
