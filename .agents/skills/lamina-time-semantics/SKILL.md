---
name: lamina-time-semantics
description: "Define trustworthy date, time, deadline, expiry, recurrence, and timezone behavior. Use when a product accepts local times, crosses actor timezones, schedules recurring work, or triggers behavior from a clock."
metadata:
  lamina:
    id: time-semantics
    problems:
      - "local time entered for another person or place"
      - "deadlines, expiry, reminders, or overdue behavior"
      - "recurring routines across daylight-saving changes"
      - "different actors see one scheduled event"
    related:
      - lamina-forms
      - lamina-side-effects
      - lamina-consistency-guarantees
      - lamina-idempotency-concurrency
---
# Time semantics

Treat time as product data with explicit meaning, ownership, conversion, and recovery. “Store UTC” and “use a controlled clock” are implementation techniques, not a complete product contract.

## Classify every temporal field

| Kind | Product meaning | Example |
|------|-----------------|---------|
| Instant | One globally ordered moment | completion audit event |
| Local wall time + IANA zone | A clock reading owned by a person or place | medicine due at 09:00 in the relative's zone |
| Date-only | A calendar date with no implied instant | birthday |
| Duration | Elapsed amount independent of civil-clock changes | retry after 15 minutes |
| Recurrence | A calendar rule evaluated in a named zone | every day at 09:00 America/New_York |
| Deadline or expiry | An instant derived from a declared start, duration, and boundary policy | invite expires 72 elapsed hours after issuance |

Do not collapse these kinds into one timestamp. In `entities[].attributes[].contract`, name the kind, owning actor/place, accepted input, authoritative representation, display policy, and correction path.

## Local wall-time boundary

When a user enters a local time for a subject-selected timezone:

1. The client submits the untouched local components plus an IANA timezone identifier and, when needed, an explicit overlap choice.
2. A trusted server validates the zone and resolves the wall time with a timezone-aware library/database.
3. A nonexistent DST-gap time is rejected with a nearby valid-time recovery. An ambiguous overlap requires an explicit earlier/later choice; never guess silently.
4. Persist the resolved instant and enough source semantics—local components, zone, and disambiguation—to audit or re-render the actor's intent.
5. Display the relevant zone or offset whenever actors may differ, and preserve one authoritative instant across all projections.

Never parse a `datetime-local` value with `new Date(value)` in the browser and then attach an unrelated timezone label. That converts in the browser's zone before the server can honor the subject's zone.

## Recurrence and operational time

- Advance recurrences by calendar rule in their named zone, not by repeatedly adding 24 hours.
- Define missed-run, delayed-monitor, duplicate-run, retry, and catch-up behavior. A participant's open browser is not an operational clock.
- Record the actor and authoritative instant for consequential completion, acknowledgement, escalation, revocation, and correction events. If the promise is “know what was done,” surface who did it and when.
- Separate an in-product overdue/urgent truth from notification delivery. Delivery failure must not erase or postpone the authoritative state.

## Graph and proof obligations

- Entity attributes classify every consequential temporal value.
- Operations define trusted resolution, preconditions, invalid/ambiguous input failures, and correction.
- Invariants preserve instant identity and prohibit browser-zone substitution.
- Dependencies name the timezone-data and independent-runner mechanism, owner, cadence/tolerance, unmet behavior, and health proof.
- Scenarios cover browser zone != subject zone, DST spring gap, DST fall overlap, recurrence across an offset change, delayed runner, and duplicate/replayed evaluation when relevant.
- Tests use a controlled authoritative clock and explicitly set different browser and subject zones. Assert persisted state and cross-actor rendering, not only form submission.

## Anti-patterns

- A bare ISO string whose product meaning and zone owner are unspecified.
- Fixed `24 * 60 * 60 * 1000` arithmetic for a local daily recurrence.
- Browser-local conversion followed by an arbitrary IANA zone field.
- Silent normalization of invalid or ambiguous civil times.
- UI-only timers for overdue, expiry, or delivery promises.
- Showing “today” or “09:00” to multiple actors without saying whose calendar or zone applies.
