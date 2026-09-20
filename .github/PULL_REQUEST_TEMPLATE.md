## What this changes

<!-- One or two sentences. What is different after this lands? -->

## Why

<!-- The problem. Link the issue if there is one. -->

## How it was tested

<!-- The compaction path cannot be exercised by `claude -p`; it is unavailable in
     a headless session. Say which kind of session you ran this in. -->

- [ ] `./scripts/validate.sh` passes
- [ ] `tsc -p tsconfig.json` passes against regenerated declarations
- [ ] Ran in a real interactive session
- [ ] Claude Code version tested against: <!-- e.g. 2.1.278 -->

## If this touches the keep-set

<!-- Delete this section if it does not. -->

- [ ] Explained in a comment why `tool_use` and `tool_result` pairs still travel
      together
- [ ] Checked that the kept set stays bounded across repeated cuts
