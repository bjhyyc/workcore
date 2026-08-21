# WorkCore Context Continuity reference architecture

Status: E6 reference protocol and executable policy model for EVT software discovery. It is not production software, a security implementation or evidence that OS/application integration works. The reference implementation is `cad/context_continuity.py`.

## 1. Product purpose

Context Continuity is the reason WorkCore must be more than a powered chair with a folding desk. It binds an authenticated person, a known physical configuration, available devices, local task references, privacy state and optional network resources into a resumable work snapshot.

The measurable product moment is not “the mast moved”. It is:

> After the user parks and requests Focus or Café work, the correct local task becomes usable within P95 10 seconds, with no cross-user disclosure, no silent camera/microphone activation and no path from restore software to movement authority.

The 10-second target is a design input inherited from the E5 product thesis. Completeness/reliability targets must be frozen from task research before DVT; a fast but incorrect restore is a failure.

## 2. Hard boundary with movement safety

The continuity engine is outside the safety-control domain.

- It may read a hardware-certified summary such as `CAFE_PARKED` or `FOCUS_WORK`; it may not infer that state from UI intent.
- Restore is rejected unless the parking brake is confirmed, the drive contactor is open and relevant mechanisms are known and locked.
- It cannot request torque, reset STO, release brakes, move a table/mast/footrest or write safety-controller state.
- A failed, slow or compromised restore leaves the product parked. Physical escape and local manual controls do not depend on it.
- Every request and rejection is written to a tamper-evident product event stream in the production architecture.

## 3. Snapshot content and explicit exclusions

Allowed snapshot fields are opaque local workspace references, required device identities, optional network-resource references, the owner identity reference, source physical state, privacy requests, schema version and timestamp.

The snapshot must not contain plaintext credentials, encryption keys, raw biometric templates, reusable UWB secrets, safety-controller memory, arbitrary actuator commands or a serialized cloud session token. Production storage requires encryption at rest, authenticated records, per-user separation, rollback protection, retention limits and an export/delete/retirement path.

## 4. Restore sequence

1. **Authenticate owner locally.** A phone/UWB presence signal is not sufficient by itself for sensitive context release.
2. **Read the independent physical safety summary.** Unknown, moving or unlocked states reject restore.
3. **Validate snapshot schema, age and integrity.** Stale snapshots require an explicit user decision; future/invalid timestamps reject.
4. **Restore the local core first.** Network loss may remove collaborative/cloud resources but cannot erase the basic workspace.
5. **Reconnect only present, authorized devices.** Missing devices produce an explained partial restore rather than silent substitution.
6. **Apply privacy monotonicity.** The current, more private hardware state wins. A remembered camera/microphone use always requires fresh consent and visible indication.
7. **Measure and log.** Record authentication, gate result, start/useful timestamps, completeness, blocked items, user corrections and any cross-user/security event.

## 5. EVT scenario set

| Scenario | Expected result |
|---|---|
| Correct user, parked Focus, all local devices present | Full local restore; no motion request |
| Correct user, no network | Local task restores; network resources are explained as partial |
| Wrong or unauthenticated user | Reject before revealing task metadata |
| Ride/Follow/unknown mechanism state | Reject and remain parked/stopped |
| Snapshot requests camera but shutter is closed | Partial restore; shutter remains closed |
| Snapshot requests microphone without fresh consent | Partial restore; microphone stays unavailable |
| Required display/storage device missing | Partial restore naming the missing device; no silent reassignment |
| Snapshot older than the frozen retention/age boundary | Require explicit confirmation or reject |
| Power loss during snapshot write or restore | Recover last authenticated record; no corrupted half-restore |
| User export, deletion, service replacement or resale | Verifiable export/delete/crypto-erase with no recoverable prior-user context |

## 6. Required evidence

- Automated policy tests on every software change, including owner mismatch, unsafe state, stale/corrupt records, offline mode and privacy monotonicity.
- OS/device adapters tested against the frozen compatibility matrix, not merely the reference planner.
- At least one complete creator/developer task chain measured from park confirmation to useful work, with machine time separated from user cleanup/setup time.
- Repeated transition and interruption tests: sleep/wake, network switch, VPN, device removal, app update, compute-module reboot, OTA rollback and storage-full conditions.
- Threat modeling and penetration testing across phone/UWB identity, local APIs, cloud/API, debug/service ports, update and supply-chain boundaries.
- Human validation that partial restore messages answer “what is missing, why, and how to recover” without sending users into unsafe mechanism workarounds.

No claim of “context follows you” is releaseable until these tests have traceable reports and the product journey demonstrates that physical cleanup, doors, charging and recovery do not erase the promised time saving.
