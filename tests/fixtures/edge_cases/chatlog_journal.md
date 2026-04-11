# 2026-04-10

Worked on the v0.8 chatlog specialist today. Phase 1 detection landed cleanly. The bounded-text design held up — every signal we wanted is computable from the decoded sample buffer.

---

# 2026-04-09

Designed the chatlog specialist. The trick was figuring out which signals carry drift and which don't. Speaker labels carry it. Section marker styles carry it. Wiki link counts carry it. Top capitalized tokens carry the most.

---

# 2026-04-08

Schema reshape day. Namespaced specialist_metadata, schema_version field, baseline_max_bytes cap. Painful but necessary.

---

# 2026-04-07

Started the project. Got the universal tier up first, then the baseline tier, then PDF specialist as the proof.
