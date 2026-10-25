> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni 0.2 Compatibility Contract — alpha.6

**Current language:** 0.2.0-alpha.6  
**Current writers:** Wave11 / logical OMC11 (`OMCX` + u32le(11)).

1. Current writers emit only Wave11/OMC11.
2. Current readers retain explicit support for Wave/OMC 1..10.
3. New semantics cannot be admitted merely by changing a version header.
4. Alpha.6 `for-each` requires Wave11/OMC11.
5. Alpha.5 View semantics retain their minimum introduction fence at Wave10/OMC10.
6. Alpha.4 product/layout semantics retain their minimum introduction fence at Wave9/OMC9.
7. Generic templates are not a historical IR form; Alpha.6 serializes only concrete specializations.
8. Existing historical expression/statement tag numbers stay stable; OMC11 appends `ForEach`.
9. Unknown extended `OMCX` versions fail closed.
10. `reference/compat/legacy1..legacy10` are self-contained migration fixtures and must canonicalize to Wave11 when admitted.

Compatibility refers to the declared semantic subset, not acceptance of malformed or version-smuggled input.
