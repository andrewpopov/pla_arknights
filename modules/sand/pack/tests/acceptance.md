# Sand module acceptance test

Goal: verify the installed MAA module on the real English Tales campaign, including actual gathering yield. Passing unit tests or a successful native API call alone does not pass this test.

Run the installed module's preflight and regression tests first. Verify the recorded anchor hashes and package manifest. Reuse its MaaCore OCR, hand detector, NativeSession lease and native Custom tasks for live actions.

Inspect the current emulator before spending an Act. If a battle is already active, pause it and preserve it; do not resume unknown deployments. Otherwise confirm the stage is Shrubbery Galore, inspect the remaining Acts and drinks, and confirm the selected operators and skills against the development route.

Live budget: one expedition, at most two existing energy drinks, no brewing, no crafting, no day advancement, and no campaign reset. Stop before starting if the visible cost/state cannot be confirmed. Do not change autoplay_enabled.

Within battle, keep the clock paused during OCR, registration and planning. Use the existing four-second gathering interval. Verify every operator identity, placement tile and facing selector. Activate Mountain S2 once. Bank only an observed nonempty load after confirmed retreat. No retries that spend another Act.

Pass requires all of these:
- Correct selected stage and route prerequisites.
- Pause transitions and camera settling confirmed.
- Blaze upper/Left and Mountain lower/Left deploy correctly.
- Mountain collects 2, Saria collects 3 and Blaze collects 3, with confirmed retreats.
- At least 8 wood appears in the actual settlement or campaign inventory increase.
- Settlement is collected and the world map return is confirmed.

If any step fails, save screenshots and the reason and leave any active battle paused. A safety stop is a passed safeguard and a failed/blocked expedition test, never a successful farm.

The runner writes acceptance.json and player.jsonl under I:/MAA-data/sand-player/acceptance-20261028. Inspect mode is non-consuming; --execute explicitly authorizes the one development expedition. It never promotes its carried-load accounting to an actual-yield success: settlement evidence must be reviewed independently.

The Młynar article and Bilibili routes are reference-only. This test validates the current modular control route, not an unimplemented guide strategy.

Recorded findings from the live test:
- HQ details were not an accepted entry screen; added an exact native observer and reused SandPilot@Back.
- Opening squad preparation could finish after the first check; added bounded recognition retries without retrying expedition Start.
- Broad OCR read Mountain as Mountaias because of an overlapping tiredness glyph. Native withoutDet card-title crops recover all three exact names on the saved failing frame.
- The selected squad visibly requires two energy drinks and stock is zero. The final test must stop before SandPilot@SquadStart.

Evidence directory: I:/MAA-data/sand-player/acceptance-20261028. The test does not claim live wood collection until actual settlement/inventory yield is verified.

Explicit recovery variant: --execute --restore-energy permits one preparation submission yielding up to two drinks. It may proceed only when the game's own raw-ingredient preview funds the entire trip. It must preserve pre-existing partial selections and buff provisions, cancel an insufficient preview, and verify the actual stock increase before expedition start. Default acceptance mode still spends no ingredients. Day progression is not performed by this runner.
