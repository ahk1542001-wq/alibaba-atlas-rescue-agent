---
name: guardian_push
description: Sends proactive Telegram alerts via the Guardian service. Use when a proactive alert is warranted (disruption, booking updates).
allowed-tools: telegram_send
---

# Procedure

1. Build the alert payload — exclude passport numbers and PII values (§9.4).
2. Wrap the sync services.guardian call with asyncio.to_thread.
3. Token present: send and report delivery status.
4. Token absent: report skipped_not_failed (graceful skip, never an error).

# Input-Output

- Input: GuardianPushInput (services/skills/guardian_push.py).
- Output: delivery_status {sent | skipped_not_failed}.

# Verification

- §8 unit suite: token absent yields skipped_not_failed, not a failure (F8).
