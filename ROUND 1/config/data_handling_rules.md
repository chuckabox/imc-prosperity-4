---
DATA HANDLING RULES (STRICT)

IMC DATA (PRIMARY)

* Split into:
  * Train: 60%
  * Validation: 20%
  * Test: 20%
* Use train for learning
* Use validation for tuning
* NEVER use test data during development
* Use test set only once for final evaluation

EXTERNAL DATA (SECONDARY)

* Located in data/external/processed/
* Used only for robustness checking
* DO NOT train on external data
* DO NOT tune parameters on external data
* DO NOT mix with IMC data

DECISION RULE

* Strategy must perform well on IMC validation
* Strategy must remain stable on external data
* Reject strategies that fail on external data

PRINCIPLE

* IMC = optimisation
* External = validation
---
