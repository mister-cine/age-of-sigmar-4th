# AoS catalogue resolver (prototype)

Python 3.10+; standard library only.

The resolver reads multiple BattleScribe/New Recruit `.cat` XML files, indexes shared entries by ID, resolves cross-catalogue `entryLink` targets, and preserves the importing node separately from its target definition. It handles XML namespaces and retains raw XML fragments for auditability.

## Run

```bash
python tools/aos_catalogue_resolver.py \
  --catalogue "Helsmiths of Hashut - Taar's Grand Forgehost.cat" \
  --out build/taar-resolved.json \
  "Helsmiths of Hashut.cat" \
  "Helsmiths of Hashut - Taar's Grand Forgehost.cat" \
  "Helsmiths of Hashut - Library.cat" \
  "Lores.cat"
```

## Important boundaries

- Supply every catalogue/library file that may contain a referenced target.
- A missing target is reported as unresolved; no name-based guessing occurs.
- Importing costs, constraints, modifiers and conditions remain attached to the link.
- Target definition, profiles, nested child entries and nested links retain their own catalogue provenance.
- This is structural extraction, not a rules legality checker or a verified rules interpretation.
- The output intentionally includes raw XML fragments to make every transformation auditable.

Run tests from the repository root:

```bash
python -m unittest discover -s tests -v
```
