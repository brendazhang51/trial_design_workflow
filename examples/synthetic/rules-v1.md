# Synthetic engineering rules, version 1

These are test conventions, not CDISC or regulatory requirements.

## copy

For auto-supported test parameters, copy the latest approved fact exactly.
Require a separate approval of the current parameter proposal and its context.
Order included records by parameter code, then assign contiguous sequence values.

## review

Missing or rejected facts and manual parameters require review. External-source
parameters require documented external review, which is not implemented yet.
Unsupported parameters remain visible. Explicit exclusions remain decisions.

## text

Configured character limits are engineering test limits only. Block overlong
values and control characters. Do not split text or assign null flavors.
