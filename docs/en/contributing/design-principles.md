# Core design principles

[한국어](../../ko/contributing/design-principles.md) · [Core contract](core-v2-spec.md)

Keep one authoritative Task aggregate. Preserve ordered skill phases and unfinished-task Stop enforcement. Use explicit IDs rather than comparing goal sentences. A failed attempt is recoverable history, not a cancelled user goal. Reads and blocker reports do not require writer ownership.

Keep actor identity, resource ownership and execution choice separate. Worktree isolation does not choose a session or provider. Original text and exact quote spans establish provenance; neither a hash nor a peer report proves human consent. Host permissions remain authoritative. The core is coordination within the host security boundary, not an operating-system sandbox.
