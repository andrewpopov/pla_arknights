# English Tales campaign module

The module is packaged with our local MAA builds. Supervised Jagged Jungle gathering delivered 15 wood on Day 3, independently confirmed at settlement and in the world inventory (8 → 23). Unattended gathering and the complete Day 1–6 campaign remain unvalidated. Runtime screenshots and guide media stay on I:.

Run `Play-Sand.cmd --check` from the MAA installation for offline preflight. No arguments also run preflight. It verifies route configuration and the recorded calibration hashes without loading MaaCore or connecting to the emulator.

A supervised development run requires `Play-Sand.cmd --execute --allow-experimental`. Keep the MAA GUI closed, use only Arkies on 127.0.0.1:16384, start at the Tales world map with Shrubbery Galore visible, and select the route's required squad first. This is one expedition, not a prosperity reset loop. There is no battle-phase resume, automatic day advance or campaign reset.

## Module boundaries

- `resource/tasks/`: existing MaaCore Custom task schema, OCR observers and navigation actions. Tasks load after the English client layer through NativeSession.
- `routes/`: stage, squad, camera coordinates and an ordered list of bounded actions. The executor supports observed DP waits, deployment with explicit facing, observed collection, confirmed banking and settlement. It accepts no arbitrary code or task names from route data.
- `guides/`: attributed observations, uncertainty and evidence references. Article pixels are not emulator tile coordinates. Guide files are never loaded as executable routes.
- `maa_sand_config.py`: validates route admission and anchor hashes before connecting.
- `maa_sand_player.py`: executes validated steps using the existing native controller and confirmation guards.
- `maa_session.py`: shared exclusive-controller lease, English resource layering, MaaCore connection and GUI conflict checks.
- Existing `maa_core_eval.py` and `replay_maa_screen_tasks.py`: saved-image verification; no emulator connection.

Scene registration is the remaining OpenCV adapter for the scrolling RA camera. It rejects weak/repetitive matches, moving cameras and invalid placement tiles. OCR, hand detection and Custom navigation use MaaCore. The supervised player uses ADB screenshots and touch under the shared NativeSession lease, plus calibrated fixed-button template matching to pause before slower OCR. Keep analysis paused and use at most five seconds of gathering between observations. Selected operator names, facing selector, load fractions and post-retreat cooldown must confirm before the next step. Skill-once preserves Mountain's stance.

## Packaging and rebuilding

`tools/package_maa_sand.py` installs `modules/sand` and an installation-level `Play-Sand.cmd`. Build-Local-MAA packages it after building Debug and runs native saved-image replay; install_maa_windows_build packages it into each new local install. Existing IS changes continue through the existing native source/resource build pipeline.

The extension contains its own Debug native DLLs because DebugImageTest is compiled out of production MaaCore. Its resources link to the same installation's resource tree; it never mixes Debug DLLs into the WPF application's root. It bundles the Python bridge and CoreEval adapter, so running it does not require the research checkout. module.json records hashes and external dependencies. A GUI task entry and a production native Sand task are not implemented.

External machine dependencies remain explicit: Windows Python, MuMu, NumPy/OpenCV at I:/MAA-data/build-tools/sand-python, and calibration anchors at I:/MAA-data/sand-player/anchors. Pinned packages are in requirements.txt. New installations preserve media and screenshots on I:; guide video files are referenced, not copied onto C:.

Install only these runtime packages if needed:
`python -m pip install --cache-dir I:/MAA-data/pip-cache --target I:/MAA-data/build-tools/sand-python -r requirements.txt`

## Adding a route

Copy a route under routes with a unique id. Declare its stage, registered camera points, required operators, steps and validation status. Keep autoplay_enabled false until saved positive/negative fixtures and a bounded live expedition verify the correct stage variant, selected skills, placement, timing, gathering yield and settlement. Replacing Młynar S3 with another chopper requires a new verified plan; an operator name substitution does not preserve the attack area.

The current development route retains Blaze S2, Mountain S2 and Saria S2 for reproducibility. It is not the extracted Młynar guide. Three operators and six both cost two drinks, so shrinking the squad does not save food. Water/pump play, energy/stock planning, raid checks and depleted-node selection remain pending.

Run focused tests with `python -m unittest discover -s tools -p test_maa_sand*.py`. Saved-image geometry tests use local I: evidence. Native replay supports --overlay and --mode battle_deployment in addition to report/OCR.

## Acceptance test

The written procedure is tests/acceptance.md. The installed module includes run_maa_sand_acceptance.py, which reuses its own MaaRuntime and SandPlayer. Inspect mode captures and recognizes the current state; --prepare stops at squad preparation; --execute attempts one development expedition only after operator identity and the visible energy budget confirm. Existing battles are paused and preserved.

Example from the installation directory:
`python modules/sand/tools/run_maa_sand_acceptance.py --module modules/sand --output I:/MAA-data/sand-player/acceptance-new-run --execute`

Use a new output directory for each attempt. The test permits at most two existing drinks and no brewing, crafting, day advancement or reset. It requires settlement/inventory evidence before claiming actual wood yield. Checkpoint exits return code 2; inspect/preparation completion is not an unattended-farm pass.

The 2026-10-28 live acceptance work found and fixed an unrecognized Headquarters overlay, a squad-opening transition race, and Mountain's name merging with the tiredness icon. Card-title fallback uses MaaCore withoutDet crops, exact names and confidence checks; it does not use fuzzy operator identity. The fixed ten-second delay after squad Start was replaced with prompt loading-state observation. Current squad stock is zero drinks; a gathering run needs two.

Energy recovery is an explicit acceptance option: add --restore-energy to --execute. Default tests still forbid preparation. Recovery verifies the raw-ingredient source, stock, ready count and an empty initial selection; AUTO only previews. It submits preparation once only if the full two-drink requirement is affordable, confirms the reward and exact stock increase, then returns through a cooking-specific native back handler. It cancels inadequate previews without spending ingredients and never retries an unconfirmed craft. Buff provisions are not consumed by this path.

The live zero-stock preview on 2026-10-28 selected all three raw foods and showed only40/60 energy, Ready0. Stored provisions were empty. Numeric counters use MaaCore ASCII recognition and a calibrated tight crop; the original Ready crop's0.729 confidence was rejected, and saved replay verifies the corrected crop at0.980. Day recovery remains supervised and separate from the acceptance test; no automatic day-skipping loop was added.

The supervised recovery attempt advanced exactly one day (Day3 toDay4), collected two rice, and verified the complete inventory supports only one drink plus20/60 toward the next (80 total). No preparation was submitted and all ingredients were preserved. Another40 energy is required for the two-drink trip. Stored provisions are empty. The target shows a hostile marker and enemy status100%; do not infer a normal harvest or a specific raid type from that icon alone. No operation was entered. The day-end step forfeited remaining Day3 Acts; Day4 retains both Acts.

Native world-hint handling now dismisses only the two observed construction/Discovery Casket banners, at most four times, before selecting a node. Unknown hints still stop at a checkpoint. The English payout button uses exact OCR. Cooking-back input is guarded by the Energy Drink screen identity; the generic text Back task cannot match its arrow-only header.

## Offline guide-derived candidate

While the user has handed app/emulator control to Solo Leveling, keep all MAA work offline: no NativeSession/Connect calls, UI inputs, restarts or installation updates. The last observed Arknights state is historical, not a license to inspect its current screen.

The recorded twelve-operator walkthrough now has a93-frame source-timestamp ledger and10 visually checked observations in guides/bilibili-shrubbery.json. Its opening is SaileachS1, MłynarS3 and Executor the Ex FoedereS3, followed by EyjafjallaS3. The visible facing chevrons in this source are Right/Right/Left for those first three; do not substitute directions from a different guide or pose. The full recording ends before a settlement screen, so its final wood/food totals remain unknown.

The source visibly shows Gavial carrying5/4 and Młynar carrying4/0, plus repeated Waai Fu collection deployments. Staged carrier accounting now assigns each confirmed deployment an ID, rejects stale/double banking before any retreat input, resets capacity evidence on redeployment and resets one-use skill state for the new deployment. Over-capacity/zero-capacity loaded readings require an adequate capacity observed in the same deployment. Empty0/0 is allowed only for explicitly declared zero_capacity_actors (or a prior nonzero capacity in the same deployment). The supported observed peak is capped at6; unsupported capacities stop. Never share a peak between operators or deployments.

guides/shrubbery-six-operator-candidate.json is a disabled proposal using six source operators, not a loadable route. Repeated permanent-DPS skill scheduling, selected-camera mapping, ownership/modules and live yield still need verification. One alternate saved selected-camera pairing passes; the current anchor and its bridge still fail the unchanged geometry guards. No threshold was relaxed and no candidate coordinates were enabled for execution.

Phantom in the Mirror has a distinct local game-data ID. Its live hand/panel identity and summon plan remain unverified; duplicate actor names are rejected rather than silently sharing a carrier cycle.


## Offline campaign plan: Days 1–6

`campaign/early-days-1-6.json` holds twelve source-referenced Act objectives. The Bilibili recording supplies Shrubbery combat evidence; the three Kuniya articles supply the campaign sequence. Source Japanese labels link to English names through campaign/stages.json by shared game IDs; source labels themselves are never English OCR aliases. Expected yields are not credited to inventory.

`maa_sand_campaign.py` reuses the module pack resolver and checkpoint errors, without importing the native runtime. It checks an explicit saved observation: day, Acts used, HQ, wood, water, drinks, raw-food energy, roster, tired names, threat status, settlement and freshness. Energy must come from the raw-ingredient preview, not an assumed rice value or stored buff meals. An urgent observed raid overrides the guide calendar. Unknown threats, inadequate food, tired members, HQ prerequisites and stale observations produce blockers. It never advances days, crafts, selects random encounter choices or connects to the emulator.

Example (historical evidence only):
`python tools/maa_sand_campaign.py --state patches/maa-sand-player/campaign/historical-day4.json`

The historical Day 4 case reports a 40-energy shortfall and HQ2 deficits of 57 wood/4 water. Construction prices are planning references and require confirmation before spending. Refresh the state only after app control returns. Map-specific water/hub/raid/talk handlers and live validation remain pending; the planner is advisory and all campaign autoplay stays disabled. Future module packaging includes both this helper and its campaign data. No current installation update is required for offline planning.


The Day4–6 deployment extraction is in `guides/kuniya-days4-6-deployments.json`: 21 hashed original screenshots saved on I:, with source timers and camera-specific observations for the mixed wood/water trip, two-hub wood trip and two-pump water trip. The Day6 water reference has an empty operator roster and still consumes drinks; planner squad_size=0 is admitted only for this objective, never for an urgent raid. State `tools` records observed name/count ownership; missing pump/hub entries produce shortfalls. The Day6 source does not show dialogue, so the earlier water_talk objective was corrected to water. Source coordinates remain non-executable. All 74 Sand tests pass offline.


## Repeated harvesting skills (offline staged)

Route action `maintain_skills` services reviewed non-toggle skills during bounded harvesting windows. It validates already-deployed actors, known SP costs, 1–5 activations per deployment, a 1–120 game-second budget and a remaining-time floor of at least25. It reuses the native OCR/operator panel and existing pause/input helpers. Each activation requires exact selected skill title and one confident READY reading, then exactly one spent-SP fraction with the expected cost and no READY. A submitted but unconfirmed click stays pending and cannot retry. Executor attack recovery is never inferred from elapsed time. Existing one-shot Mountain behavior is unchanged.

Native saved-image replay of the video Młynar panel reads1/42 at confidence0.997977 using the new SP crop. This proves the crop reads that saved cooldown panel, not live activation or English title/READY recognition. The six-operator guide includes an uncalibrated action proposal; no executable route was changed. All85 offline Sand tests pass, including command/observation tests and route-admission checks. Live title/READY/click confirmation remains pending while Solo Leveling owns app control.


## Observed settlement rewards

`maa_sand_settlement.py` uses the existing MaaCore MatchTemplate and regional ASCII OCR to bind each quantity to an identified reward icon. Five saved English icons cover wood, water, gold, Fowlbeast Wing and Wild Plant in the first six result slots. It requires the result header and exact operation stage, rejects conflicting slots, and reads one confident explicit +N gain. A low-confidence counter gets one magnified-crop retry through native OCR on a1280x720 canvas; thresholds remain unchanged.

Saved native replay verifies the two historical reward sets: wood2/water1/gold2/wing1/plant1 and wood11/gold3. All quantity confidences exceed0.996. Independent moved-icon matches pass; loading/battle negatives miss. See guides/settlement-assets.json for source/template hashes. Missing icons are unknown, never zero; unknown items and full inventory remain unresolved.

The runner records this evidence before dismissing settlement and saves the verified world-return image. Acceptance reports distinguish observed wood yield/target from controller banking estimates. Reading failures preserve the result checkpoint. This is wired into future local builds, with93 offline tests passing, but remains uninstalled during the Solo Leveling handoff.


## Exact campaign stage identities and raid references

`campaign/stages.json` joins English/Japanese game exports by stageId and levelId, recording both source hashes. Known stages are Shrubbery Galore (sandbox_1_01), Jagged Jungle (sandbox_1_38), Within Range (sandbox_1_40), Drinkwater as Bait (sandbox_1_55) and Straight Into the Abyss (sandbox_1_56). Campaign loading rejects guessed or inconsistent names/IDs. Passive native stage observers issue no inputs. Saved replay verifies the Shrubbery result label at0.944339; the other four English stage observers still need positive fixtures.

Complete cached guide sets on I: contain38 Day2–3 screenshots and61 Day4–6 screenshots. New guide references record the six-person Day3 river raid team (Fang, Vanilla, Kroos, Ansel, Midnight, Popukar) and Day5 Jagged Jungle raid team (Fang, Midnight, Popukar, Beagle, Ansel, Lava), plus source deployment milestones. Raid screenshots use kill counts, not gathering timers; the gathering runner must not run those maps unchanged. Exact facing and later deployment identities remain unverified.

Only hub-based objectives require HQ2. Dialogue and raid objectives are no longer incorrectly blocked at HQ1. An urgent raid clears the previous harvest stage ID, English name, equipment requirements and deployment reference before proposing interception. Guide dates never establish an observed raid. All97 Sand tests pass offline; active app control and installation remain untouched.


## Raid HUD and harvesting admission

`maa_sand_battle.py` parses only confident K/T kill counts with K<=T and a positive total; timers, contaminated OCR and impossible counts are rejected. Lives are a separate confident numeric observation, never assumed. Progress deltas reject changing totals, backwards kill counts or increasing lives within the same audited battle.

Native saved-image replay with regional ASCII OCR verifies0/42,5/42,41/42 and6/44 with3 lives, including the opening frame. A tighter kill crop excludes the adjacent goal icon; confidence thresholds were retained. Three gathering/result negatives fail the raid parser. Source hashes and expected observations are in tests/raid-hud-cases.json; these Japanese guide HUD fixtures do not prove English live execution.

The existing harvesting runner now recognizes raid HUDs for pause handling only, records the observation, and stops paused before harvesting deployments. Timer-based gathering and deployment calls reject raid mode. Acceptance retains raid observations and preserves existing battles. This does not implement raid combat or wave tactics; exact English HUD fixtures, live pause confirmation and a calibrated raid handler remain pending. All106 offline Sand tests pass.


## Bounded pump preparation and tool costs

The saved English UI and current game export call the wood device Sawing Harvester Hub, not the older Basic Gathering Hub alias. Required tool names in the campaign and guide data now use the current name. campaign/tools.json binds item IDs to exact English names and prices: Crabbie Pumpie10wood; Sawing Harvester Hub7wood+1stone, HQ2. These are planning references, not permission to ignore the visible recipe.

`ToolCrafter.prepare_pumps(target=1, reserve_wood=0)` starts only from the workbench or exact pump recipe. It reuses SandPilot@PumpRecipe and SandPilot@CraftOnePump, admits targets1–2, requires existing quantity1, exact visible cost and confident stock, and checks the full missing batch plus reserve before the first craft. Each single craft must confirm exactly one added pump; an unresolved submission remains pending for this helper instance and blocks further submissions. The helper is available through SandPlayer.prepare_pumps but is not called by the default route or acceptance test. Inventory is not updated from expected spending. Hub crafting and tool equipping/deployment remain unimplemented.

Native saved-image replay verifies pump title0.958783, recipe stock0 at0.997291, quantity1 at0.998497, wood13/10 at0.969285, and the later workbench pump name/stock1 at0.999812/0.959208. A narrow high-threshold binarization crop corrected the original weak stock read; confidence admission stayed0.85. The cached native observations also pass the helper through a mock runtime, with no emulator or real crafting.

Campaign advice budgets missing tools by their complete recipe, including stone for hubs; unknown stone is not assumed affordable. Owned tools do not trigger unnecessary material requirements. All121 offline Sand tests and Ruff pass. The active MAA installation remains unchanged during the Solo Leveling handoff. Live crafting transitions still require validation after control returns.


## World observations and operation reconciliation

`maa_sand_world.py` reuses native Tales Act1/Act2/NextDay templates and adds passive day/HQ/resource counters. Every material count requires its matching fixed HUD glyph and a confident numeric reading. A world-map control plus day-label or exhausted-day proof is required. Missing/covered counters remain unknown; the arrow replacing the day number proves zero Acts but not the day number. Near-tied Act template scores remain unknown.

Native English saved replay verifies Day2,2Acts,HQ1,gold5/water1/wood3/stone1/rice2; an exhausted-day frame preserves unknown day/rice; Day4 dialogue preserves unknown gold. Battle and payout screens are rejected. The inherited Act1 template still needs a positive English fixture. Source glyph hashes and cached observations are in guides/world-hud-assets.json and tests/world-hud-native.json.

The runner records world observations after settlement; acceptance captures before/after facts and compares same-day Act differences and reward/resource deltas. It resets the baseline after explicitly collecting a day payout. It rejects a known day change or an Act increase within a known day, and cannot prove a one-Act operation when either day is hidden. These reports do not establish campaign continuity, spend Acts, calculate food energy from rice, advance days, or update inventory/freshness automatically. Raw food, drinks, rested roster and threat observations remain separate prerequisites. All132 offline tests and Ruff pass; no live validation or installation occurred.


## Video opening calibration candidate

SceneMap feature extraction now excludes the fixed PAUSE/Game Paused rectangle (490,300,320,155). Those UI descriptors must not supply map geometry while the camera moves. Match count, ratio, spread, reprojection, scale and viewport thresholds are unchanged. A regression proves pause text alone supplies no map features. Existing saved-scene tests still pass.

With that exclusion, three independent registration paths map the video opening into a separately pinned Saria-selected emulator view: Młynar normal761,288 / selected823,282; Executor Alter normal675,367 / selected745,365; Saileach normal774,440 / selected839,424. Path disagreement is1.47/3.59/1.61 pixels respectively. Source tile annotations retain roughly10pixels of manual uncertainty, and registration consistency is not live placement proof. See guides/shrubbery-opening-geometry.json for image hashes, source points and limitations.

The alternate selected reference is copied under I:/MAA-data/sand-player/calibration-candidates/shrubbery-video-opening. It is incompatible with the default side anchor and is not loaded by the existing route. The saved populated field has an occupied Executor target (green fraction0); the two other targets are green in that fixture. Fresh tile legality, hand/camera identity and observed facing remain required. The opening mapping is non-executable; collector/buffer placement and full-route validation remain incomplete. Default route coordinates and anchor pins were not changed. All134 offline Sand tests and Ruff pass.


## Cooperative skills and collector evidence

Optional route background_skills specs use the same exact actor/SP/cycle validation as maintain_skills. The player services only matching active deployments before each bounded collecting/DP advance. It preserves the last25game seconds by default for banking, skips absent/retired actors, and stops before advancing on uncertain activation. A full carrier returns with its verified panel open for banking before any other skill panel can intervene. The six-operator guide proposal now uses this cooperative mode instead of a blocking120second wait. No existing route enables it.

The Waai Fu field inspection at video400seconds supplies one collector correspondence through the source idle view. An independent persistent Młynar position check differs by2.96pixels. Chained projections are about normal517,304 / alternate-selected597,325, with15pixel manual annotation uncertainty; direct emulator matching failed, so this is reference-only. See guides/shrubbery-collector-geometry.json. Do not treat it as validated Gravel/Yato substitution: Waai Fu silence has separate utility. Nian and right-side collector field registration still fail; three other accepted image transforms were hand previews, whose assumed tile centres were explicitly discarded.

This work uses saved media only. No source coordinates became an executable collector route, no thresholds were lowered, and no app/installation was changed. All141 offline Sand tests and Ruff pass, including collecting/skill interleaving, late reserve, full-carrier banking priority and invalid background configuration.


## Day 4 NPC visit and encounter energy

The Day 1–6 campaign explicitly separates world encounters from expeditions. Day2 Act2 and Day5 Act1 world encounters do not require expedition drinks or rested operators. An observed urgent raid overrides that plan and restores combat squad and energy requirements. Day4 Act2 uses an empty squad and no tools in the guide, but still spends two drinks and one Act; Day6 water gathering also supports an empty squad. No empty combat squad is admitted by these exceptions.

`maa_sand_dialogue.py` prepares the exported Liaison first-contact sequence: nine spoken lines and six single-option decisions. The packaged plan stores canonical text fingerprints, source hashes and guide image references. Each line requires exact canonical body and speaker matches at confidence0.85 or better; choices use only the verified text rectangle. The passive DialogueLog task clears the inherited bulk-click subtask. Advancement uses the existing single native click task, never the ten-click opening chain. Unknown tokens stop; unexpected gameplay returns are paused and rejected. After the complete known sequence, gameplay pause must be confirmed. Quest save and route unlock remain explicitly unverified.

Saved English tutorial frames verify DialogueLog positives0.945935/0.956241, two non-dialogue negatives, body confidence0.960394–0.984953, speaker0.992036 and choice0.957460. These are different story tokens and are rejected by the Liaison plan. Actual English Liaison positive frames, empty-squad launch, final save/unlock verification and campaign continuity remain pending. The helper is packaged but is not called by the default route or acceptance test. All153 offline Sand tests pass; no app control, live input or installation occurred.


## Day 6 water completion

The guide leaves after two pumps have produced a visible +20 water haul. It does not require waiting for timer expiry: pumps are present at03:36, absent at02:16 and the bag is inspected at02:13. Those timestamps are source observations, never a fixed wait script. The Day6 Act2 campaign step now references guides/day6-water-completion.json, including an empty squad, two pumps, two drinks, one Act and separate save/settlement verification. An urgent raid clears this completion reference.

`maa_sand_bag.read_bag_water` uses passive native matches for the open-bag header and water item, then reads a confident explicit +N label relative to that item. It excludes the bottom warehouse row, whose25water in the guide is not the current20water haul. Missing water is unknown, never zero. `water_goal` compares the observed haul to guide strategy targets10/20 for one/two pumps; these are policy targets, not asserted universal production capacities. It returns readiness for saving while keeping settlement required and inventory unchanged. It issues no inputs.

The template source replays as bag+water and native OCR reads +20 at0.998791. English settlement/paused screens and the guide battle frame reject both icons. A further98 independent guide images have no bag matches; no independent bag positive or English bag positive was found. Thus the source-image self-match is not English layout validation. Assets, hashes and cached native results are packaged. Live tool equipping/deployment, correct water tiles, English bag recognition and save/leave transitions remain pending; the default route and active install remain unchanged. All162 offline Sand tests and Ruff pass.


## Shared pump and hub preparation

ToolCrafter now handles both reviewed recipes with one bounded batch engine. prepare_hubs(target=1, observed_hq=2, reserve_wood=0, reserve_stone=0) is exposed through SandPlayer. The caller must supply a current observed HQ level of at least2; the helper does not refresh world state itself. It requires the exact English Sawing Harvester Hub recipe and quantity1, complete wood/stone price labels, whole-batch affordability and both reserves before spending. Each single craft must confirm stock+1. Day6's two hubs cost14wood+2stone; Day4's one costs7wood+1stone. Current game-export prices and names are checked against the reviewed catalog.

Pump preparation keeps its existing native OCR fields and workbench stock confirmation. Hub preparation reads both ordered material labels in one bounded region, with one full-canvas magnified native OCR retry using the existing settlement enlargement helper. The helper reopens the exact hub recipe to confirm stock when crafting returns to the workbench, rather than reading an adjacent card's count. One shared pending state blocks switching between pumps and hubs after an uncertain submission. A confirmed operation may switch recipes, with new identity/material checks. There are no default-route or acceptance calls to prepare_hubs.

Saved guide image43 shows quantity2 and prices19/14wood and4/2stone. Initial OCR read only9/14 and was rejected as incomplete. A magnified replay read19/14 at0.999549 and4/2 at0.997749. Quantity2 reads at0.960122; execution deliberately preserves it and stops, because this helper submits individual crafts and requires quantity1. The Japanese guide does not validate the exact English hub title: native hub-title recognition rejects that frame and English pump/workbench negatives. English hub positive and live navigation/crafting/stock transitions remain pending. All174 offline Sand tests and Ruff pass. No app control, crafting, rebuild or active-install update occurred; the source candidate on I: is updated separately.


## Combined campaign tool preparation

SandPlayer.prepare_campaign_tools(state, reserve_wood=0, reserve_stone=0) now dispatches the next Day1–6 Act's required_tools through one shared ToolCrafter.prepare_batch. It requires a current settled observation, known threat timing, HQ prerequisites and enough existing drinks/raw food to fund the complete trip. It skips harvest preparation when an urgent raid overrides the calendar, both Acts are used, or the next step has no tools. Raw food being sufficient is not cooking confirmation; this method does not brew, launch or advance days.

The batch visits every requested recipe and reads exact identity, quantity1, stock and material prices before the first craft. Common material quantities must agree across the inspection. Day4's pump+hub batch requires17wood+1stone when both are missing. Subsequent recipes' costs are reserved during each craft, so the pump cannot consume the hub's seven wood. Requested construction reserves apply in addition to the entire batch. Existing tools are confirmed and not crafted again; expected stock must remain unchanged between inspection and execution. Every submission and stock increase uses the existing single-recipe engine and its shared pending state. Partial failure stops without automatically crediting inventory or retrying uncertain crafts.

Recipe switching reuses Tales@RA@CancelCraft. The new derived tasks explicitly bind Tales@RA@Craft.png: Debug resource loading caught that default derived-template names otherwise refer to missing files. Corrected native replay recognizes the English recipe's control at0.990650 and rejects the workbench and battle negatives. This proves recognition, not the live close transition. The source-only candidate includes the campaign dispatch and batch engine; default autoplay/acceptance flows do not invoke them. All191 offline Sand tests and Ruff pass, including integrated Day4 preparation, two-hub Day6 preparation, whole-batch insufficiency, construction reserves, material/stock drift and unknown-modal handling. English hub positive, live recipe switching/craft stock proof, tool equipping/deployment and full campaign continuity remain pending while Solo Leveling owns app control.


## Named campaign formation and Tools-tab access

`maa_sand_navigation.CampaignNavigator` provides shared navigation for the five reviewed campaign stage IDs. It handles visible node selection by exact canonical English name, confirms the selected right-sidebar title, then uses a native chain that rechecks the same title before the existing Start task opens formation. An existing unrelated formation is first returned to the world and reentered through the requested named stage. Unknown states, wrong sidebars and formation timeouts stop. Unexpected gathering/raid battles use the existing BattlePause control once, require pause confirmation and stop navigation. There is no battle-start, day-advance, map-panning or route-unlock action in this helper.

`SandPlayer.prepare_campaign_formation(state, request_tools=True)` selects the next current settled campaign Act through this navigator. Unknown threat timing, urgent raids without a named interception map, world encounters and spent Acts do not dispatch calendar battle navigation. When the Act requires tools it requests the exact lower Tools tab, whose English formation view otherwise leaves the tool column off-screen. The returned checkpoint deliberately leaves squad and equipped-tool verification false; clicking a tab does not prove contents, quantity or even the panel transition. Tool selection quantities and actual equipping remain unimplemented, and this path is not invoked by the default route or acceptance run.

Recognition-only native Debug replay confirms the English Straight Into the Abyss world node at0.964626 and node-selector recognition at0.968561, selected Shrubbery sidebar/native formation-title guard at0.984821, and the lower Tools button at0.996812. The battle negative matches none. The water label lies atY558 and was outside the previous stage observer region endingY500; stage scans now extend toY625. Node selectors exclude the sidebar, while details tasks inspect only the sidebar. The stage catalog records saved-image evidence separately and keeps execution_calibrated false. Other stage English positives, live navigation/tab transitions, off-screen nodes, actual tool equipping and combat route validation remain pending. All206 offline Sand tests and Ruff pass. MAA/emulator and active installation remain untouched during Solo Leveling's app-control handoff.


## Ingredient-derived campaign funding

campaign/food.json joins all21 raw FOODMAT drink-conversion records to exact English item IDs/names in the exported game data. Rice gives20energy; Fowlbeast Wing30, Wild Redhorn5 and Woodchip Fungus5. Fowlbeast Wing is sandbox_1_poultry; sandbox_1_wings is the distinct Feather Dust item worth5, so similar names must not be substituted. Cooked FOOD records are excluded. The60energy drink denominator comes from the verified cooking UI.

Campaign state may now supply raw_food_inventory keyed by exported IDs and raw_food_inventory_complete. Advice derives energy from those counts and rejects a conflicting legacy raw_food_energy total when inventory is complete. Incomplete observations remain a known lower bound; absent ingredients are not claimed to be zero. Legacy explicit raw_food_energy input remains supported. No inventory capture or freshness is inferred by this calculation.

With explicit food_spendable_ids and optional food_reserves, maa_sand_food.plan_drinks computes a bounded candidate allocation for the missing0–3drinks. It first minimizes energy above the target, then item count, and cannot spend more than observed stock minus reserves. Ingredients omitted from the spendable list remain protected. Insufficient observed spendable food produces no partial selection. Existing drinks reduce the target. Both selected quantities and excess energy are advice only: visible cooking preview and actual stock confirmation remain required, and overflow retention is explicitly unverified. The existing AUTO cooking implementation is unchanged. A current idle-cooking observation may additionally supply `stored_drink_energy` (0–59), `stored_drink_energy_verified: true`, and `stored_drink_energy_image`. Positive carry without both verification and an image is rejected. This energy reduces only the ingredient target: e.g. verified carry40 plus2 Rice at multiplier2 funds a two-drink preview. It never credits prepared drinks or predicts future overflow. Refresh both ingredient stock and stored energy after cooking before planning another trip.

Campaign tool preparation uses the spendable-food shortfall after reserves. Thus six Rice can fund two drinks mathematically, but reserving one leaves20energy unverified for that trip and prevents the Day4 tool batch from spending materials. The synthetic campaign/examples/day4-reserved-food.json exercises this case; it is not a current game snapshot. All218 offline Sand tests and Ruff pass, including exhaustive small-inventory allocation comparisons. Guide/tool-selection dialog evidence remains missing; no equip controls were invented. Native app/emulator control and active installation remain untouched during the Solo Leveling handoff.


## Reviewed world encounter branch

The Day2 guide's Japanese Slightest Effort panel joins to scene_business_2_enter by the identical event scene ID in the English export. The three choices cost one Act each: sell5Crab Claws for90–110gold, sell3Puffball Tenderloins for110–130gold, or Give them a free ride for55–65gold with no listed ingredient cost. The source guide goes from6to61gold, consistent with the free-ride branch. Its subsequent Alright acknowledgement has costAction0. The catalog does not expose generic machine-readable reward/cost transitions; this is a manually reviewed narrow policy, not an automatic interpretation of all223choices.

maa_sand_encounter.CampaignEncounter and SandPlayer.resolve_campaign_encounter(state) handle only an already-opened exact Slightest Effort panel during the next reviewed encounter Act. They require complete title/body fingerprints and all three option matches, current day/Act HUD agreement, and a native option rectangle within the choices region. The one-Act submission remains pending until the exact reviewed result and zero-cost acknowledgement return observed world facts with a one-Act difference. An uncertain submission cannot be repeated by the same helper. Unknown events, changed days, unknown states and urgent raids stop. World reconciliation preserves unknown day when the final Act turns the day number into an arrow; neither the reward range nor route unlock is credited to inventory.

Recognition-only Debug replay on saved English A Note validates the shared title/choice regions at0.995829/0.996649 and rejects Slightest Effort/free-ride identities on that unrelated event. It also supplies the previously missing English one-Act positive: second-squad.png matches WorldActs1 at0.981909, with WorldActs2 rejected; day-two-ready.png matches WorldActs2 at0.979413. Battle matches none. These are calibration/negative fixtures, not an actual English Slightest Effort positive. The handler and references are packaged; default route/acceptance do not invoke them. Map encounter opening, other encounters, actual English result recognition and live reward/Act reconciliation remain pending. All228 offline Sand tests and Ruff pass. Unexpected battle frames reuse the named navigator's single-pause recovery and preserve the pending encounter submission. No app control, installation or emulator input occurred; the explicit handback question remains pending while Solo Leveling owns control.

## 2026-10-29 merged build notes

The encounter registry now dispatches the exact reviewed Slightest Effort and Day 5 Exchange Troubles branches. Exchange Troubles spends one observed Act; its free leave option is not the paid guide branch. Pending submissions prevent switching policies. Expected gold is advisory and never credited as observed inventory. English positive captures and live result transitions remain pending.

Food catalog energy values are nominal. Raw-ingredient calculations require an explicitly verified multiplier of 1 or 2; the active game multiplier is unverified. This supersedes any earlier implication that the nominal catalog automatically gives the active mode yield. Brewing still verifies the native preview and actual stock independently.

## Guide empty-squad formation preparation

CampaignNavigator.prepare_empty_next and SandPlayer.prepare_empty_campaign_squad support the reviewed Day4 Act2 Liaison visit and Day6 Act2 water run. They reenter through the exact named stage, use the existing native Tales clear-squad and red-confirm templates as individual bounded actions, and require all seven Add Squad Members labels afterward. A preexisting confirmation is never accepted. An uncertain clear remains pending across calls on the same helper; unexpected battle frames use the shared pause recovery. Already empty formations are preserved without clearing. No battle is started, tools are not equipped or credited, and the trip still requires two drinks. The native Delete may clear equipped tools as well; the subsequent loadout must be checked independently.

Saved English formation replay recognizes Delete at0.995422 and the empty seventh slot at0.975244; occupied slot1 is rejected. Battle and world negatives reject all four probes. English fully empty formation, confirmation positive and actual clear transitions remain unverified. This helper is not called by default autoplay or acceptance. It remains offline while Solo Leveling owns emulator control.

## Stage-bound route camera manifests

The shared player now honors each route anchors.idle and anchors.side filenames instead of always loading idle.png/side.png. Other reviewed campaign stages use CampaignNavigator.prepare_formation through their canonical stage_id. They require an explicit pack-relative anchor_manifest with schema_version1, the same stage_id, an asset location and SHA256 pins for both named camera files. Manifest path escapes, missing hashes, changed image bytes and name/ID mismatches are rejected. Camera pins are checked again in the player constructor before image mapping or inputs. The legacy Shrubbery route retains its existing two hashes, entry flow and autoplay-disabled status. No new route or coordinates were invented; these are prerequisites for calibrating the remaining maps, not proof of a working campaign.

Basic tool catalog records now join exported itemTrapData to bundled battle_data: Crabbie Pumpie is trap_403_wfactory; Sawing Harvester Hub is trap_401_xbfato. Both are TRAP units with position NONE in the data; that field is not a live placement permission or facing observation. Their exact English names agree across both sources. Saved native hand replay detects six ordinary operators in the English control screenshot but no cards in the two2532x1170 guide images. Debug stretches those non16:9 images, so the misses do not prove tool detection is unsupported. No global hand thresholds or templates were changed. Tool selection/deployment and map camera calibration remain pending, with emulator access explicitly withheld for Solo Leveling.

## Observed Day6 water completion

WaterHarvestMonitor in maa_sand_bag shares the existing player capture, pause, advance and native bag reader. It pauses before opening the identified bag control, reads current-operation water, closes the bag and confirms a paused battle. The harvesting clock must be unchanged during inspection. Read failures still attempt bounded bag closure and pause restoration; uncertain toggles remain pending and cannot be resubmitted. Missing water stays unknown instead of becoming zero. Between observations the monitor advances at most five wall seconds, budgets actual observed game-time decrease and preserves at least25game seconds even at2x. Timer resets, decreasing water, exhausted bounds and unverified state stop. Countdown OCR now requires confidence0.85 or higher.

SandPlayer.wait_for_water exposes the reviewed one/two-pump target10/20 only for Straight Into the Abyss. A wait_water route step must immediately precede finish and cannot follow an unbanked collection. Reaching the target returns paused and runs the existing route finish. Before reward dismissal, the named settlement must independently show at least the target water. Expected pump yield and bag readings never update warehouse inventory. An insufficient or unidentified water reward preserves the result screen for review. No existing route enables the new action; tool loadout/deployment and water-map anchors still require live validation.

The bag-button template comes from a saved English battle frame. Its source and idle.png are byte-identical copies and count as one positive, not independent validation. An actual English open-bag frame and live toggle transitions remain pending. Native app/emulator control and the active install are untouched during the Solo Leveling handoff.

A second native replay on the distinct wire-worker/00086-wait-dp.png English frame recognizes the bag button at1.0 and rejects an open-bag header. The Japanese guide open bag matches the header at0.997397 but rejects the English toggle template; its widescreen/dimmed layout is not live English transition proof. Cached fixture hashes distinguish the independent frame from the original duplicated source.

## Existing native tile-grid projection for the five campaign maps

MAA already bundles Arknights-Tile-Pos data for all five reviewed reclamation maps. The offline Debug evaluator now exposes tile_projection(stages), reusing TilePack::find_level/calc and its TileCalc2 math. It accepts exact canonical stage IDs, refuses ambiguous shared codes, requires no image or device, and returns both nominal1280x720 camera projections with raw terrain/height/buildable metadata. replay_maa_sand_tiles.py validates canonical exported level IDs, unique complete tile coverage and zero-shift/unverified-camera metadata. The receipt pins the DLL, overview.json and each actual map JSON, refusing resource drift during evaluation. English tile-index overrides require explicit provenance rather than silently using a different source. The tool is included in Sand packaging and requires a Debug core containing this mode.

Native execution produces192Shrubbery tiles,156Jagged Jungle,228Within Range,221Drinkwater as Bait and238Straight Into the Abyss,1035total. The first three guide opening positions identify the same native cell in normal and selected poses: Młynar[7,11], Executor[6,12], Saileach[7,13], expressed as zero-based[column,row]. Annotation offsets remain4–11pixels. This is nominal grid alignment, not a verified live camera or green placement/facing.

An independent source-frame search also found four collector projection paths, but their predictions disagree by13.14pixels. The nearest nominal cell is initially forbidden, with22–35pixel offsets. The collector is not assigned a verified map tile; dynamic resource clearing, annotation and nonplanar registration need resolution. No six-operator substitutions, new route or autoplay were enabled. The Debug core was rebuilt for offline validation only; the installed MAA and emulator remain untouched.

## Collector height hypothesis: ruled out

The native offline tile projector now also reports a diagnostic floor plane through the existing TileCalc2 functions, using the map own floor elevation. It preserves the original terrain, height and buildable fields, with explicit floor_plane_live_verified=false. rank_waypoint_tiles compares initial/floor models and always returns execution_allowed=false; neither a close fit nor a floor projection proves a cell was cleared or permits deployment. All original native projected points were compared with the prior report and remain unchanged.

The disputed nearest Shrubbery cell[4,11] already has height_type1, so its initial and floor-plane projections are identical. This rules out the height explanation for the22–35pixel collector offsets. A1080p frame extracted from the existing recording at400seconds shows the unit contact area obscured by its attack effect. The original point is explicitly unverified; it was not replaced with an assumed sprite-foot or attack-range-centre coordinate. Source waypoint origin and local camera registration still need resolution before binding a collector tile. No route was enabled or installed, and no emulator input occurred.

## Bounded Day4 first Liaison visit

LiaisonVisit and SandPlayer.visit_campaign_liaison(state) connect the existing named-stage navigator, empty-squad preparation, exact Liaison dialogue and shared settlement return. The current Day4 Act2 plan must target Drinkwater as Bait, have known nonurgent threat and two prepared drinks. The caller must explicitly supply liaison_intro_pending=true from current observations; day number alone never establishes this quest condition. The helper captures the world and checks day/Acts/HQ agreement, reenters the named stage, and requires all seven empty operator placeholders plus the visible first empty tool placeholder1/12. Tools owned in inventory are not the same as equipped tools.

Before Start, the complete drink cost/stock badge must show cost2 and stock matching the state. Native OCR on the English fixture reads a high-confidence partial-2, which is deliberately rejected. One shared settlement magnification retry reads the whole-2/4 at0.951646; split or slashless fragments are never combined into a ratio. Start is submitted once. Only a confirmation arising after this owned launch may be accepted, at most once. Unknown states, repeated confirmations, insufficient drinks and unknown dialogue keep the transaction pending. Unexpected battles reuse the navigator pause recovery. Exact known-script completion must return a confirmed paused field before the existing finish handler leaves, reads the named result and verifies world return plus observed Act difference1. No day advance, inventory credit, actual drink-debit proof, quest-save proof or route-unlock proof is inferred.

The existing player CLI accepts --visit-liaison --campaign-state PATH --check for a connection-free plan check. Execution additionally needs --execute --allow-experimental and passes the same live controller checks. This does not run the Shrubbery strategy; the shared finish handler accepts the explicitly reviewed visit stage. Default autoplay/acceptance do not call the visit.

Saved native replay self-matches the English empty first tool placeholder at0.999681 and rejects the battle and source equipped-pump screen. Actual English fully empty formation, English launch-warning positive and live launch/dialogue/leave transitions remain pending. The Japanese wide warning does not match the canonical English-sized confirm template; no threshold was lowered to force it. The caller-supplied pending-intro observation is not independently recognized by this helper. App control remains with Solo Leveling. A ground-only collector-registration probe also failed the unchanged distinct-match gate; its trial masks were not promoted to calibration.


## Guarded field tools (offline implementation)

`SandPlayer.deploy_tool(item_id, slot, direction=None, maximum=2)` shares operator hand detection, settled camera registration, green-tile checks and placement gestures. Only the reviewed basic pump and harvester identities are accepted. Both camera points must already be calibrated. The complete English name must be confident, the native hand must show sufficient DP and a known cost, and the logical slot must be vacant. Each item is limited to one or two deployments per operation.

Tool instances are tracked separately by slot and never enter carrying, retreat banking or expected-yield accounting. A pending record is written before the placement swipe; an ambiguous input, facing selector or field-name check blocks later deployments. Tools without an observed selector may use direction=None; an observed selector requires an explicit direction and uses the existing measured diamond gesture. A field name confirms identity at the mapped slot, not independent orientation or inventory debit.

No route enables this API yet. English tool-hand detection, live placement/facing, loadout selection, per-map anchors and consumption still need bounded validation after the emulator handoff. Active installation and autoplay remain unchanged.


Route steps may now use `deploy_tool` with exactly `item_id`, `slot`, `direction` (null only for a tool without a facing selector) and `maximum` (1 or2). The operation budget must remain identical for each instance of an item. Operator and tool slots cannot overlap; tools cannot be collected or banked as operators. Tool routes must remain experimental. A water route must explicitly deploy its declared pump count before its final `wait_water` step; it cannot assume a previous expedition's pumps or expected yield. The executor stops on a placement failure before another tool or settlement action. Existing route files and the nonempty-squad requirement are unchanged; the empty-operator Day6 launch still needs its own verified loadout/start flow.


## Native raid backend audit

MAA already provides `SingleStep` copilot actions through `SingleStepBattleProcessTask` and `BattleProcessTask`; a separate raid gesture engine is unnecessary. The local source now stops a single-step batch when `do_action` fails and reports cancellation as failure. `SingleStepTask` disables retries for these action batches because earlier actions may already have deployed units. Ordinary Copilot behavior is unchanged.

This does not enable raid execution. The shared battle engine's wait conditions can poll until an operator/DP/kill condition is met; the caller still needs a bounded deadline and a verified pause on timeout. Its nominal TilePack projections do not establish the current reclamation camera, live stage/wave identity or the actual source-guide deployment tiles. The current guide evidence has unverified later operator identities/facing, and English raid result handling remains pending. Tool-selection dialogs are absent from saved English evidence: the reviewed formation shows only the edge of the tool tray; native Tales tool tasks craft items rather than equip them. No selection coordinates or raid routes were invented from these gaps.


The bounded acceptance runner now shares the Liaison visit's complete trip drink-badge reader instead of the old broad OCR crop. It uses `SandAuto@FormationTripEnergy` and at most one existing fourfold crop retry, requires a confident whole cost/stock ratio, and preserves the two-drink limit. The recorded native raw `-2` is incomplete; the independent magnified read `-2/4` can fund a bounded run. Ambiguous, low-confidence, underfunded or three-drink readings stop before launch. This is saved-image evidence, not a new live transition test.


## Data-backed tool planning

`extract_maa_sand_mechanics.py` joins the exact reviewed item/trap/phase/level/skill records from three hash-pinned English game tables. The source is ArknightsAssets/ArknightsGamedata, also used by MAA's resource-update workflow, pinned to commit409bce70516f2420af61b1fc5680da60e448ab99. The previously cached Kengxxiao overseas repository is archived; existing camera and guide evidence was preserved rather than silently replaced. Full raw tables remain on I: under sand-guides/20261029/game-data/409bce70516f; the compact extracted catalog is campaign/tool-mechanics.json. The extractor is included with the module for reproducibility.

Campaign advice now includes required-tool base DP/HP/defense, exported placement descriptions and raid exclusions. The pump skill exports live_duration85; 110seconds includes its full exported lifetime plus a25second exit reserve, not proof of a water yield. The hub exports initial SP15/cost20 and max_cnt3, so advice reports a5SP gap and3-gatherer cap without inventing a current activation time. Its wood/stone/iron hp_ratio parameters are retained as parameters, never converted into delivered item counts. Both basic tools are listed in battleExcludedTrapsInRush. Client version, modifiers, orientation, live placement and resource delivery remain unverified. These advisory values never replace fresh DP, green-tile or settlement checks.


## Full exported map context

`maa_sand_levels.py` reads the five pinned full level records from the same English export commit as the mechanics catalog. It compares every tile key, height and placement type against MAA's compact map grid; all1035cells match. Original game-object positions use bottom-origin rows, so the explicit conversion is `[col,height-1-row]`. Jagged Jungle's exported extra-route entrance `(row2,col0)` maps to MAA `[0,9]`, and its goal `(row6,col12)` maps to `[12,5]`. The converter rejects fractional, boolean and off-grid object positions.

`campaign/level-rules.json` preserves predefined object candidates with their activation unverified, both main and extra route sets, complete wave actions, branch alternatives and random group/weight/refresh fields. `level_reference` in campaign advice exposes candidates and alternative counts without choosing an active branch. Relative wave/fragment delays are not absolute battle timestamps; random resource candidates are not current stock. Branch route-index binding, live objects, camera pose and execution remain unverified. Urgent raids still remove the calendar stage rather than inheriting its resource reference.

The Liaison export links the two initial NPC variants to the exact first-conversation dialog, but its quest display records do not contain a usable current-availability predicate. The hidden Meet the Liaison quest has null displayed text. These records do not replace the current pending-intro observation required by the visit helper. No additional quest unlock or save flag is claimed.


## Day 1–6 execution (2026-10-30)

`campaign/early-days-1-6.json` remains the calendar and stage identity source.
`campaign/day-execution.json` adds per-Act recipes, observed reward floors,
quest/raid evidence requirements, and day-end construction reviews. Source
payout examples never update inventory. Positive-wood floors are operational
checks, not proof that the guide yield or HQ construction target was reached.

`tools/maa_sand_days.py` connects the existing player, encounter, Liaison,
world-HUD, drink-cost and settlement helpers. `DayRunner.run_day(observe)`
accepts a new observed state for each Act and stops after the current day.
`run_act(state)` is also exposed through the installed `Play-Sand.cmd`:

```powershell
Play-Sand.cmd --campaign-act --campaign-state I:\MAA-data\sand-player\observed.json --journal I:\MAA-data\sand-player\campaign.json --route reviewed-day1-route --allow-experimental --execute
```

The state uses the existing campaign fields plus an explicit `campaign_id`
and unique `observation_id`. Read-only review without connecting:

```powershell
python tools/maa_sand_days.py --state observed.json
```

The journal records `pending` before any native input. A timeout, missing
world return, or ambiguous Act debit stays pending across restarts. A consumed
Act with insufficient or unknown rewards becomes `needs_review`; neither state
is automatically replayed. Inspect actual evidence before manually resolving
an entry. Do not delete a pending journal or stale lock merely to retry.

The Day6 two-pump recipe can be compiled offline:

```powershell
python tools/maa_sand_days.py --water-calibration reviewed-water-slots.json --output day6-water.json
```

Calibration must name stage `sandbox_1_56`, a stage-bound `anchor_manifest`,
`normal_points` and `side_points` with separate `pump1`/`pump2` slots,
explicit `directions` for both pumps, and `water_tile_evidence`. These are
reviewed inputs, not coordinates inferred by the compiler. Place the generated
route in the pack's `routes` directory only after reviewing it with the existing
route/anchor checks. It remains experimental. The routine uses actual DP,
deploys two pumps, monitors bag water20, and saves/leaves with a 25-second reserve.
An empty squad is accepted only for this two-pump Abyss route; the native player
rechecks all seven empty slots and submits at most one launch confirmation.

Current boundaries: map calibration and live resource performance are still
unverified. The old zero-wood development route is explicitly rejected by the
campaign backend. Tool Acts require an actual equipped-tool verifier (not an
inventory count); the CLI does not yet provide one. Raid combat, event-node
opening, quest save/unlock verification, HQ/planter construction, and automatic
fresh roster/food/threat observation remain separate work. Existing dialogue or
encounter return alone cannot certify progression. No day advance is automated.
No emulator control was used for this offline implementation.


## Source routine compiler (2026-10-30)

`tools/maa_sand_day_routes.py` compiles six harvesting Acts through the existing
native player's route schema: Days1/2/3 carrier harvesting, Day4 pump plus hub,
Day6 paired hub teams, and Day6 two pumps. The video opener is a separate Day1
strategy (`strategy: "video-six-operator"`): Saileach Right, Młynar Right,
Executor the Ex Foedere Left. Its existing cooperative skill specifications
are reused. The article strategy keeps Młynar Left. The six-operator video
adaptation still lacks verified Nian buff timing; it is not a reproduction of
all twelve operators in the recording.

```powershell
python tools/maa_sand_day_routes.py --day 6 --act 1 --calibration reviewed-hub-slots.json --output I:\MAA-data\sand-player\day6-act1.json
```

Every output remains experimental. Compilation validates with `load_profile`,
including actual action fields, camera-anchor stage binding, DP bounds, slot
occupancy, carrier collection/banking, tool counts, and settlement termination.
It does not promote unknown coordinates, facings, resources, or guide timestamps
to observations. `campaign/route-calibration-requests.json` lists the exact role
bindings and evidence still needed. These requests contain no runnable pixels.

Wood routines require explicit `collection` trips and `chop_game_seconds` from
reviewed evidence; the guide does not establish the precise carrier rotation.
Costs come from `dp_costs` keyed by operator/tool name, and `directions` is keyed
by slot. The video requires its three separately named opener slots. All wood
routines service the configured background skills during bounded advances.

Day4 deploys the pump, downward hub, below-hub Młynar, and reviewed left-side
defender. It uses actual bag water10, then checks the named Within Range
settlement. Shared water completion now binds either reviewed stage explicitly;
it cannot accept a different map's settlement. Day6 uses lower hub → Spot →
Ansel → upper hub → Beagle → Hibiscus. The passive harvesting action reads the
actual game clock between pause windows, checks continuity, and stops with a
30-second exit reserve or a bounded timeout. Delivered wood is still verified
only at settlement; waiting is not a resource credit.

Carrier collection now stops at the25-second reserve even if the load remains
zero or unreadable, avoiding the previous extra unobserved advances. These
changes do not provide tool selection, raid combat, or quest construction.
Saved English formation evidence exposes only the tool tray edge, so equipped
tool recognition remains unvalidated. The user reconfirmed Solo Leveling owns
the emulator; no live captures, launch, or gameplay occurred.


## Delivered hunting food and reward crop fallback (2026-10-30)

Day1 Act2 now checks at least80 base ingredient energy from exact, delivered
raw-food rewards in the named Straight Into the Abyss settlement. The source's
two sliced pieces are `sandbox_1_venison`, English Puffball Tenderloin and
Japanese まんまるスライス, worth40 base energy each in the cached exports. Leg Meat
is a different item (`sandbox_1_beef`,60). The original guide description is
retained alongside the canonical item ID in `guides/kuniya-day1.json`.

`verify_hunting_food` binds each positive count to a confident item icon and
explicit `+N` quantity evidence in a distinct reward slot. Known Fowlbeast Wing
rewards can contribute their exported30 base energy as well. Generic wild
plants, unmatched icons and absent counters remain unresolved. No food stock,
prepared drinks, conversion multiplier or complete inventory is inferred.
`NativeDayBackend` now derives `food_reward_verified` from this report instead
of leaving it as an unimplemented outcome flag.

`SandAuto@SettlementTenderloin` uses a50x45 icon crop with threshold0.9. A native
102-frame saved-image probe found the source crop and two independently reviewed
result positives (0.979709 and0.985643), with no match on the English formation
and battle negatives. `campaign/tenderloin-recognition.json` pins the source,
export tables and template. Its actual English tenderloin positive remains
unverified; these source-panel preparations are recognition evidence only,
not live battle coordinates.

The original32-pixel counter crop can clip the plus sign from two-digit gains.
A wider crop recovered source `+10` at0.990176, but degraded some existing English
single-digit confidence. The reader therefore retains the original crop first,
then tries `SandAuto@SettlementCountWideN` only after a real parse/confidence
failure, followed by at most one magnified retry. Strict `+N` grammar and the
confidence threshold remain unchanged. Each reward records which crop supplied
its evidence.

A reusable no-controller regression command runs the full named-stage reader:

```powershell
python tools/replay_maa_sand_settlement.py --runtime modules/sand/runtime --output I:\MAA-data\sand-player\settlement-replay --stage "Shrubbery Galore" --image saved-result.png
```

The replay copies input evidence to its output directory before magnified
retries, preserving the original files. It never connects to or controls the
emulator. Hunting deployment, tool selection, map calibration and live Day1
completion still require separate verification.


Full native English-reader regression preserved the earlier observed result
(wood2, water1, gold2, Fowlbeast Wing1, unresolved wild plant1) and read the second
result as wood11/gold3. The first result retained primary crops throughout;
wood11 used the new bounded wide crop. This verifies the existing English reader
path, not a live hunting run or an English tenderloin positive.


## Bounded raid combat takeover (2026-10-30)

`tools/maa_sand_raid.py` compiles the reviewed Day3/Day5 examples and runs a
separate already-open raid battle through `SandPlayer.deploy_raid`. It reuses
the existing native hand recognition, selected-camera registration, green-tile
check, facing gesture and field-name confirmation. Harvest deployment remains
blocked in raids. Combat deployments use a separate identity ledger and never
credit carrying capacity or banked wood. Facing is requested through the shared
gesture; it is not independently range-verified yet.

```powershell
python tools/maa_sand_raid.py --day 5 --calibration reviewed-raid-slots.json --output I:\MAA-data\sand-player\day5-raid.json
Play-Sand.cmd --raid-profile I:\MAA-data\sand-player\day5-raid.json --check
```

Calibration supplies stage ID, pinned `anchor_manifest`, both camera point
maps, `slots` keyed by operator, `directions` keyed by slot, `dp_costs`, explicit
`deployment_order` and `placement_evidence`. Day5 additionally requires
`late_actor_evidence`; its verified opener is Fang → Midnight → Popukar → Ansel.
The later Beagle/Lava order must be reviewed. Day3 order is entirely explicit.
The compiler requests deployment as soon as actual DP permits; screenshot kill
counts are observations, not deployment wait triggers. Source wave totals44
and42 are examples and must match the observed HUD. Dates are not wave identity.

`campaign/raid-skills.json` pins skill1/rank7 titles and SP costs for the eight
source operators using the existing exported character/skill tables. Fang and
Kroos are automatic; the manual policies include Vanilla, Midnight, Popukar,
Beagle, Ansel and Lava. The shared verified skill-click helper requires exact
skill title, READY and confirmed spent SP. An ambiguous click stays pending and
cannot be clicked again. Actual owned levels/ranks and live skill UI behavior
remain unverified.

Once emulator control is returned, the bounded execution form is:

```powershell
Play-Sand.cmd --raid-profile I:\MAA-data\sand-player\day5-raid.json --journal I:\MAA-data\sand-player\day5-raid-journal.json --raid-run-id day5-observed-raid-A --allow-experimental --execute
```

It requires a fresh zero-kill raid, actual initial lives, empty local deployment
ledger, matching wave total and registered stage camera. Paid deployments and
skill submissions are journaled before input. DP/kill waits, total wall time,
life-loss budget and manual skill uses are bounded. Progress must remain
monotonic; stale/missing HUD readings stop execution. Game advances are at most
two seconds, shortening near the end. Life loss beyond the profile budget stops
paused. A result screen ends combat actions immediately, including before all
planned deployments, and remains uncollected for review.

This mode does not launch/intercept raids from the world, establish victory,
prove final lives preserved, dismiss rewards, return to the world or advance
the campaign. The campaign backend still refuses to substitute harvesting for
an urgent raid. `result_pending_review` is a preserved checkpoint, not a clear.
No emulator capture or action was performed during this implementation.


## Raid result collection and guide-goal update (2026-10-30)

`maa_sand_raid_result.py` adds the missing result-to-world handoff. It requires
the existing English Items received control, the distinct raid-result badge,
one confident exact `remaining/total` reading matching the owned wave, and the
existing exact English stage/reward reader before any acknowledgement. The
clean counter crop is `[270,335,70,23]`; one existing native magnified retry is
allowed. No slash repair, digit guessing or confidence reduction is used.
Saved native source replay reads `0/44` at0.990036 and `0/42` at0.993317. The
badge self-matches at1.0 and matches the independent raid result at0.999843;
the tested ordinary result and battle negatives reject it. The actual English
raid-result positive and live transition remain unverified.

Victory requires the terminal live HUD to have all enemies killed and positive
lives, agreeing with zero result remaining. Preserved lives additionally require
agreement with the owned initial lives and a monotonic, image-bound HUD trace.
A last observation such as41/42 followed by result0/42 leaves victory and final
lives unverified. A result counter alone cannot fill the missing final life
reading. Contradictory counts or a different wave stop before acknowledgement.

The collector persists `collection_submitted` before one invocation of the
existing native `SandPilot@GatherResult`, which has no repeat chain. It then
requires a newly captured world HUD. An ambiguous click or missing world return
cannot repeat that invocation. Collected rewards and the raw world observation
are retained, with no inventory credit, Act-debit claim or day-advance action.
Unproven victory/lives return `raid_world_returned_needs_review`.

New compiled raid profiles enable `result_collection_enabled`. Existing profiles
withfalse retain the old result checkpoint. This supersedes the earlier section's
unconditional result-stop behavior. The campaign backend still needs actual
raid interception/launch before it can own a complete raid Act; battle takeover
and world return do not supply the missing prelaunch Act observation.

The primary cached guide prose explicitly targets approximately30 wood for
Day2 Act1 and Day3 Act2. Their contracts now require30 delivered wood instead
of the earlier one-wood software floor. The author also says Day3's source raid
used no manual skills, so its compiled baseline sets `manual_skills_enabled=false`.
A reviewed calibration can override that policy; Day5 keeps manual policies.
These are guide-derived operational goals, never assumed inventory gains.


## Raid Act launch integration (2026-10-30)

`maa_sand_raid_launch.py` connects the existing named-stage navigator, formation
checks, raid executor and result collector to the campaign Act journal. Use
`--campaign-act --raid-profile <calibrated-profile>` with the campaign state
and journal. Battle-only takeover remains available without `--campaign-act`.
This supersedes the earlier missing-interception limitation.

The observed state must include `raid_reachable: true`, `raid_stage_id` and
`raid_enemy_count`. A reachable later raid is eligible, as in the Day3 guide;
the calendar alone never proves reachability. The selected details must show
both the raid marker and interception control, with the exact English map label
bound to that marker. The source roster must already be selected, rested, and
verified by the existing squad reader. Automatic roster selection is still absent.

Before one paid Start, the workflow requires the actual two-drink cost, matching
stock, and existing empty-first-tool-slot evidence. Launch intent is saved first;
timeouts and uncertain transitions cannot repeat Start. A recognized battle is
paused immediately before further analysis. An ordinary battle or different wave
is preserved paused. The existing combat and result modules then supply a fresh
world return, and exactly one observed Act debit is required. Unknown victory
or final lives remains a review checkpoint in the parent campaign journal.

The shared harvesting prelaunch budget check also now compares the cost, stock
and funded fields individually. Comparing the whole dictionary incorrectly
rejected valid native readings because they include an evidence field.

Saved native replay recognizes the independent source raid marker at 0.976674;
the interception control currently has only a self-positive. Tested English
ordinary details, formation and battle negatives reject both. These recognition
assets still need actual English raid positives and live transition validation.
No game connection or capture was used. Profiles remain experimental and require
map calibration; tools, hunting deployments, construction, marked NPC progression
and the full Day1–6 sequence still need completion and live verification.


## Day1 hunting compiler, recall and food-driven completion (2026-10-30)

`maa_sand_day_routes.py --day 1 --act 2` compiles the article hunting routine
against reviewed calibration. It retains Gravel, Kroos, Adnachiel, Ansel, Steward
and Plume in the source formation. The deployed sequence is pump, Kroos,
Adnachiel, Gravel, recall Gravel, then Steward. No Ansel/Plume deployment is
identified in these screenshots, so the recipe does not invent one.

Every used slot needs registered points in both camera poses, explicit facing,
observed DP cost, and water/hunting coverage evidence. The reviewed
`gravel_recall_remaining` must be greater than25 and at most180 seconds, with
`hunting_timing_evidence`. Source present-by screenshots never fill this target.
The old `hunting_finish_remaining` field is rejected: the routine now uses the
joint `wait_hunting` action immediately after Steward is deployed.

The shared `recall` action identifies the active actor and actual cargo before
using existing retreat controls and cooling confirmation. Empty recall ends the
deployment without resource credit; positive cargo uses verified banking.
Uncertain retreat stays pending and cannot be clicked again. Explicitly collected
loads still require `bank`.

`HuntingHarvestMonitor` reuses the existing paused bag toggle, clock checks,
bounded advances and reserve handling. Exit requires water10 and food80 from the
same bag image. Currently only exact Puffball Tenderloin art with a confident
explicit +N label is recognized in the bag. Each supplies40 base ingredient
energy; neither conversion bonuses nor warehouse quantities are applied.
Unrecognized food remains unknown. One native magnified quantity retry is
allowed without digit repair or lowered confidence. A decreased food count,
clock reset, unreadable counter, unresolved toggle or exhausted reserve stops.
A ready joint target exits without waiting for a fixed finishing timestamp.

The campaign preflight rejects water-only or insufficient food monitors for
Day1 Act2. Settlement independently verifies delivered water and exact food
before acknowledgement; bag evidence never substitutes for rewards. All
accounting remains observational, without inventory mutation or day advance.

Saved native replay of119 images found only the source food-bag frame and its
normalized copy as Tenderloin positives. The source +2 reads at0.999683; the
production readers jointly verify water10 and food80. The water-only bag leaves
food unknown, and three saved English non-bag screens reject food accounting.
This is a source self-positive, not independent or live English validation; see
`campaign/hunting-bag-recognition.json`. Live camera, hunting coverage, operator
availability, bag recognition and delivered yield still need validation. Seven
harvesting/hunting Acts can now be compiled; the full Day1–6 campaign remains
incomplete pending map calibration, selection and construction/NPC progression.


## Equipped-tool proof (2026-10-30)

`maa_sand_equipment.py` implements the read-only callback already required by
`NativeDayBackend.before_launch`. The campaign CLI now supplies it. The callback
requires the actual English formation control and binds its proof to the exact
formation image used for the trip budget. It compares the entire observed
loadout with the Act requirement, not merely the presence of one desired tool.

Supported observations are one or two Crabbie Pumpies, one or two Sawing
Harvester Hubs, or the one-card-per-type mixed loadout used by the guide. At most
two selected card rows are supported. Native icon matches require at least0.95;
actual quantity digits require at least0.85. A small badge can use one existing
four-times magnified native OCR retry on its numeral-only subcrop. No count repair or stock inference
is allowed. The compact selected prefix must end in a distinct empty tool slot
with the correct next ordinal and exact /12 capacity. Conflicting, repeated,
unknown, noncontiguous or clipped cards stop before paid Start.

Native component replay reads the saved guide loadouts as pump1, pump2, hub2
and the independent mixed pump1/hub1 formation. The pump template transfers to
an independent screenshot at0.963531; the hub transfers at0.995262. The mixed
quantities read at0.941024 and0.952936 after the numeral-only retry. A wider
badge crop had failed confidence0.85 and was rejected; the threshold was kept. The clipped English formation,
battle and result negatives reject. Guide component observations explicitly
leave formation_verified=false; they do not satisfy the production English
formation guard. A later live takeover verified the English one-pump loadout; see the update below.

The current observer covers the reviewed full right-hand tool pane. The saved
English operator view cuts off the quantity badge; that view is intentionally
insufficient. The existing Tools-tab request remains a calibration checkpoint.
Automatic tool selection and the remaining English loadout variants still need live
evidence. The one-pump Tools-view layout is now verified. Verification itself issues no clicks,
selection, crafting, inventory changes or battle launch. See
`campaign/tool-loadout-recognition.json` for provenance and remaining limits.


## Journaled HQ1-to-HQ2 progression (2026-10-30)

`Play-Sand.cmd --upgrade-hq2 --campaign-state <state.json> --check` reviews the
construction prerequisite without a controller connection or battle-camera
assets. `campaign/examples/hq2-offline-review.json` is deliberately historical
and blocked; its stock values never authorize execution. A real run requires
fresh settled observations, known nonurgent raid timing, `--journal`,
`--allow-experimental` and `--execute`. It uses the existing native runtime,
Headquarters/Back controls, world reader and atomic ActJournal machinery.

The workflow supports only HQ1 to HQ2, with the actual English panel showing
target2, survival at least1/1, and exact owned/cost ratios for wood60 and water5.
World stock must agree with those panel readings before one Upgrade submission.
A durable journal entry precedes navigation; submission is persisted before the
paid input. The separate `.hq2` sidecar prevents uncertain or completed
upgrades from replaying. Success acknowledgement and return controls are also
one-shot. Unexpected recognized battles are preserved paused.

The existing world HUD owns level proof. The large HQ digit is overlaid on the
camp graphic and is not used to infer a level. English HQ details verify the
actual calendar day before and after the upgrade, including zero-Act day end
where the world reader leaves day unknown. Completion requires a fresh world
showing HQ2, unchanged Acts, the exact60-wood/5-water debit and no changes to
unrelated observed resources. It never advances the day or credits inventory.
An ambiguous control, unreadable ratio, unexpected debit or missing world
return leaves a pending checkpoint.

Native saved-image replay reads the actual English unfunded panel as3/60 and
1/5 and refuses to treat it as funded. The calendar reads day3 at0.999796 after
one native magnified retry. Separate funded guide components read77/60 and
10/5; component proof alone cannot authorize an upgrade. Funded and unfunded
icon variants use separately reviewed count crops, without lowered confidence
or digit repair. See `campaign/hq-upgrade-recognition.json`.

The funded English panel, English success modal and complete paid transition
still need live validation. The source success-check icon is not proof of an
English success screen. Planter placement, marked base NPC progression and
automatic day-end orchestration remain separate unfinished pieces. No emulator
capture or input was used during this implementation.


## Optional extra planter stock (2026-10-30)

`Play-Sand.cmd --prepare-planter --campaign-state <state.json> --check` reviews
the source Day4 construction step without a controller or battle anchors. The
blocked `campaign/examples/planter-offline-review.json` illustrates the shape.
Current observations must include planter_stock, planter_placed, and explicit
construction_reserves for wood and water. Execution additionally requires
--journal, --allow-experimental and --execute. The reviewed baseline is HQ2
on Days4–6 with a visible world day and at least one Act remaining; the guide
schedules it after Day4 Act1. An unaffordable optional planter can be deferred.

`PlanterCrafter` reuses the existing ToolCrafter engine for affordability, stock
confirmation, pending-craft handling and native recipe cancellation. The
separate building catalog pins sandbox_1_building_1 / trap_456_xbfarmm and the
exported water10/wood30, output1, HQ2 recipe. It does not add buildings to the
field-tool deployment catalog. A shared before_submit hook persists actual
recipe evidence before the single paid Craft. Existing stock skips spending.
A changed stock, deployed count, budget or missing complete reserve stops.

Stock and deployed/MAX4 are observed separately before and after crafting.
The workflow confirms a fresh world return, unchanged day/HQ/Acts, the exact
material debit for zero or one confirmed craft, and no unrelated observed
resource changes. Its terminal status is ready_for_placement. Placement, saved
layout and rice production remain unverified: crafting alone never supplies
extra drinks or daily rice. Ambiguous submission or return stays pending in
a .planter journal sidecar and cannot resubmit.

Native saved-image replay reads the guide recipe as stock0, quantity1,
deployed1/MAX4, water15/10 and wood49/30. The actual English locked workbench
provides positive category/back controls and a negative unlocked-recipe case.
The locked screen's raw counter-like text is rejected by the fraction grammar;
a battle negative is also rejected. No confidence reduction or counter repair
is used. The unlocked English recipe, stock transition, world return, and all
placement/save controls still need live validation. See
campaign/planter-recognition.json. No emulator capture or input was performed.


## Planter layout save verification (2026-10-30)

`maa_sand_layout.PlanterLayoutCommit` implements the save-and-reopen half of
placement. It reuses the construction pause/checkpoint helper, native OCR,
world reader and the planter-stock ActJournal. A future calibrated placement
actor must supply distinct original baseline/before/after captures inside its
active runtime output. There is no public placement CLI or automatic drag.

Admission requires the actual English build editor, an owned stock receipt,
HQ2 capacity4, and one owned planter moving from stock to deployed count.
Both recipe observations must preserve the world wood/water balance. Durable
intent precedes the single Save. Guarded exit and HQ reopen inputs are also
one-shot; unknown dialogs and unresolved transitions leave a pending record.
Completion needs the increased saved count after reopening and a fresh world
with unchanged resources, HQ, day and Acts. It neither advances the day nor
credits rice. Saved count does not establish safe tile location or production.

Native Debug saved-image replay recognizes the actual English editor and the
HQ1 Planting Box Group row as1/2 on Day3. This capacity2 observation cannot
authorize the HQ2 workflow. The independent guide Save icon matches0.956942;
the Back icon has only its original English self-positive. Thresholds remain
0.85 for OCR and0.95 for templates. Actual English HQ2 counts, unlocked recipe,
placement selection/drag and live Save/exit/reopen effects remain unverified.
See `campaign/planter-layout-recognition.json` for provenance and boundaries.
No emulator capture or input was used.


## First base-upgrade NPC conversation (2026-10-30)

The Day3 guide image36 identifies npc_guide_trmedic1: its Japanese final line
and stone5 reward match the paired exported English/Japanese scripts. The
second NPC variant shares that final line but grants a different item. The
source also contains explicit NPC withdrawal and save commands; these are
expected script effects, not observed campaign completion.

`maa_sand_base_npc.BaseNpcDialogue` starts only at the exact first English line.
It reuses the Liaison exact-token/speaker recognizer and verified single-choice
rectangle, native advance action, camp-specific return/pause guard, and ActJournal.
It records intent before every input. A pending or observed conversation
cannot be submitted again, including an uncertain gift choice. There is no
uncalibrated map/NPC click.

Before dismissing the gift it requires the exact final line and speaker plus
the identified stone icon and explicit count5. Acknowledgement is one-shot;
the same final line must then appear without that icon before advancing it.
Unknown text, mismatched rewards and unresolved transitions remain pending.
The terminal status dialogue_observed_paused leaves inventory_updated,
quest_save_verified, route_unlock_verified and npc_withdrawal_verified false.

Native Debug saved-image replay reads the source count5 at0.998416 and rejects
English build/HQ negative frames. The icon has a source self-positive only;
this is not a complete English dialogue positive or live transition proof.
Marked-NPC initiation, English text geometry, reward acknowledgement, camp
return, actual stone delta and persistent save still require validation.
See `campaign/base-npc-recognition.json` and
`guides/base-npc-first-upgrade.json`. No emulator capture or input was used.


## Timer-free camp return correction (2026-10-30)

The base camp has no gathering countdown. BaseNpcDialogue therefore has its
own return guard instead of inheriting the Liaison gathering-timer condition.
It identifies the actual English camp exit, bag and tent, requires dialogue
absence, submits the existing native pause control only when needed, and
rechecks camp identity plus pause on a fresh capture. A recognized field or
raid is preserved paused and rejected. Unknown scenes receive no blind input.
The routine still does not leave camp, credit stone, prove NPC withdrawal or
certify a persistent save.

Native Debug replay passes independent saved running/paused English camp
frames. The upstream broad exit template initially scored0.930087 on running
camp and failed the0.95 admission rule; a tighter English exit-icon crop fixes
recognition without lowering the threshold. Running-frame bag/tent matches
are0.999789/0.999714; the independently paused exit match is0.986557. Exit
loading frame, build editor and HQ detail negatives reject. This verifies the saved
default camera reader, not a live dialogue-to-camp pause transition or camera
variation. See `campaign/base-camp-recognition.json`. Emulator control remains
with the user's other application.


## NPC exit and observed world reward (2026-10-30)

A calibrated caller can pass original pre-conversation world and HQ calendar
captures to BaseNpcDialogue.run. Both must be distinct files inside the active
runtime output. Native readers require HQ2, a matching Day3–6 calendar, known
Acts and stone. This baseline is persisted before the first dialogue input;
a dialogue-only invocation cannot later authorize exit/reward reconciliation.
The caller still owns capture freshness and uninterrupted campaign continuity.

After the owned dialogue and identified gift, return_world confirms paused
camp, records intent, then invokes one bounded copy of the existing native
LeaveCamp/ConfirmLeaveCamp chain. Uncertain exit can resume observation without
submitting the chain again. Unexpected camp, dialogue or field stops; recognized
field is preserved paused. Unknown loading screens receive no further input.
World proof requires exactly stone+5, unchanged known unrelated resources, HQ2
and Acts. At zero Acts the world day is unknown, so it opens HQ once for a fresh
calendar check and returns once before final world verification. Neither this
workflow nor a source-script save command certifies persistent quest save,
route unlock or NPC withdrawal; it does not update modeled inventory.

The historical guide-check log records LeaveCamp followed by an English world
map. Its intermediate 00008-camp-exit.png is black loading, not an exit-dialog
negative or confirmation positive. The new task aliases reuse that native
chain with maxTimes1 for both exit and confirmation. Actual English confirmation,
NPC reward/world delta and full live return remain unverified. No new emulator
image or input was used. See `campaign/npc-return-recognition.json`.


## Executable base NPC mode (2026-10-30)

`Play-Sand.cmd --base-npc --campaign-state <state.json> --check` reviews the
first NPC routine without opening a controller or loading battle-camera assets.
`campaign/examples/base-npc-offline-review.json` is intentionally blocked and
illustrative. It is not an observation of the user's campaign. State requires
Day3–6, HQ2, known Acts, a current settled observation, known nonurgent threat,
explicit campaign/observation IDs and first_base_npc_pending=true for dialogue.
Execution requires --allow-experimental, --execute and --journal. The shared
construction CLI owns the runtime lease, off-C output rule and result log.

The default npc_operation is dialogue. Start it only when the exact first
English NPC line is already displayed; this mode does not select the NPC.
It runs the reviewed sequence and preserves the confirmed camp pause. The
journal uses a .base-npc sidecar and prevents repeating the gift choice.
A CLI dialogue-only run does not create a pre-conversation world baseline.

npc_operation=return resumes only an owned completed dialogue whose baseline
was bound before the first input by the calibrated caller. Preflight verifies
that receipt's campaign, gift, day, HQ and Acts. Missing, foreign, mismatched,
pending-dialogue or already-completed receipts stop before controller creation.
No CLI option accepts old screenshots as fresh baseline proof. The library's
return_world can observe recovery after uncertain exit without repeating the
exit chain. Neither mode advances days, credits modeled inventory or proves
persistent save/NPC withdrawal. The mode cannot combine battle, route, visit,
HQ or planter modes. Actual English full-dialogue and live CLI validation are
still pending while the emulator is reserved for another application.


## Live takeover findings (2026-10-30, America/Los_Angeles)

The emulator was explicitly returned for control. MAA logged in, selected
Tales Within the Sand from the theme list (the featured theme was the newer
Relaunch Anchor), resumed the existing Day4/HQ1 campaign and verified a free
camp visit. Camp entry was preserved paused; its exit confirmation matched
0.997829 and the world return preserved both Acts and all observed resources.
This does not prove the first NPC dialogue, five-stone reward or persistent
quest save. The guide's Rhodes Island Operator was absent; the different marked
Mail Box was left alone.

Live formation navigation exposed an undefined observer: RaidBattle is a
Python-derived state, not a native TaskData entry. MaaRuntime.matches now
expands it into actual RaidKills/RaidLives observations and applies the existing
strict fraction parser. This fixes native Debug task rejection in navigation
and pause guards. Unreadable counts do not invent a raid, and the virtual
result never certifies its stage or route. Real live raid-positive validation
remains separate.

Returning from camp recentered the map and put Shrubbery Galore's complete
label at x0. The previous node crop began at35 and could not recognize it.
Extending only this selector to[0,100,860,525] matched0.966469 and reached the
correct formation through the existing named-stage chain. No battle started.
See campaign/navigation-recognition.json.

The English Tools tab supplied the missing selected-card positive. Its pump
icon begins at x951, outside the old x970 boundary. The unchanged template
matches0.981120; widening the reviewed right pane to x920 preserves threshold
0.95 and reads quantity1 at0.973305, followed by actual empty slot2 and /12.
The same-frame English formation guard also passes. The native fixture in
tests/english-pump-loadout-native.json protects this layout regression. This
verifies one English pump; English hubs, two-pump loadouts and tool selection
still need evidence. It does not prove a funded launch.

The formation had zero drinks. Provisions were empty. The existing bounded
recovery routine previewed only one new drink while the trip needs two, then
cancelled its own selection and confirmed zero ready/selected energy without
brewing. Ingredients, Acts and the current day were preserved. Recovery-day
selection is a separate decision; no reset, paid recovery or day advance was
performed during these checks.

### Outpost raid HUD stop guard

The actual English Desolate Interception Point counter sits farther left than the
previous guide crop. The wider raw counters pass all eight Debug replay fixtures,
including the live 0/44 frame. See `campaign/raid-hud-recognition.json`.

Play, formation navigation, and camp return also check MAA's existing
`BattleOfficiallyBegin` control template. If numeric battle identity fails while
those controls are visible, the shared guard requests one pause, verifies it,
and stops. It does not guess the stage or continue deployments. The unknown-HUD
guard passed a live identity-withholding test in the free camp, with pause and
return to Day 5 confirmed and no Act spent. Outpost combat retry remains
unverified. The exact Gathering Grounds label search also covers the visible
world map after camera recentering.

### Owned-team stance and outpost support

The raid skill catalog includes source rank-7 S2 records for Blaze, Mountain,
and Saria. Mountain's Sweeping Stance activates at most once per deployment;
Blaze and Saria use automatic skills. Actual selected skill/mastery identity
still requires native verification. Adjacent-tree harvesting refuses the
Mountain stance, and the experimental development route keeps it off.

Desolate Interception Point is in the canonical catalog. Preparation reuses the
raid marker and exact opened title, searching the world map with at most two
pans if the marker is hidden. Six saved English native cases pass, including
negative and clipped-marker cases. Native tile projections are diagnostic;
selected-camera calibration and successful combat remain unverified.

The observed old campaign used Challenge Mode. The opening-guide calibration
uses Standard Mode; food conversion must use its explicitly verified mode
multiplier, rather than assuming the guide and campaign share a difficulty.

### Fresh campaign introduction

`Play-Sand.cmd --camp-intro --check` reviews the exact English introductory
script without connecting. Execution requires `--execute --allow-experimental`,
`--journal` and `--intro-run-id`. The shared dialogue engine journals each input,
resumes only an owned unambiguous token, and verifies the free camp is paused
at completion. The live first line matched the source; the full journaled actor
has not yet been validated live. The separate user-requested click-through
completed the introduction and returned to Day 1 with two Acts.

Default Shrubbery preparation now uses the same named navigation as the day
routines, checking the exact opened stage title before entering formation.

### Fresh Day 1 collection findings

The current world wood crop excludes both neighboring icons and passes the
fresh zero and historical world fixtures. The carrying reader first uses raw
native OCR of the actual fraction, then falls back to normalized glyphs; it
still requires a slash and this deployment's capacity history. Normal Mountain
was observed at block/carry1, while this account's Hoshiguma was observed at4.
The development route now requests Mountain1 and remains a calibration route,
not proof of the campaign's first wood10 target.

Collection budgets use observed countdown differences, including time spent
opening operator panels. A full carrier below the requested target stops for
replanning. A timer-only native crop retries a low-confidence broad clock crop
without lowering the confidence threshold. A rejected green-tile placement
cancels its positively identified hand card, preserving native hand detection.
An exit retains battle state until the result is identified and pauses if the
field remains active, without repeating the exit.

The four-operator test banked Mountain1, Blaze3 and Hoshiguma4. The borrowed
right-facing source position produced Saria0 in this run. Eight is below the
pump target. Emulator recovery verified Day1, one Act left, wood8 and gold3;
the settlement screen itself was not captured. These
observations do not enable autoplay or certify the Day1–6 campaign routines.
The next opener needs the guide's stronger chopper and actual resource coverage.

Owned guide squad (2026-10-31): `shrubbery-guide-mlynar` is compiled through
`maa_sand_day_routes` from `calibration/shrubbery-mlynar-owned.json`. Młynar
E2 level90 S3 rank7, Beagle/Spot/Cardigan level55, and Noir Corne/Yato level30
were selected and observed. Native formation validation pairs an exact observed
Młynar glyph variant with the selected S3 icon on the same card. Battle identity
requires the complete selected S3 title; canonical name matching remains exact.
The roster scrolls horizontally. Guide-specific chopping coverage and carrier
rotation are still experimental; the previous four-operator trip delivered8 wood,
which did not meet the first pump's10-wood budget. No Day1 completion is claimed.

Chopper calibration correction: guide image12 places Młynar two columns east of
its collector, at the eastern cell previously field-verified with Saria. The
experimental adjacent upper cell filled Młynar to3/3 during S3. The current guide
candidate uses normal `(766,290)`, selected `(829,283)`, facing Left; this exact
Młynar coverage is still awaiting its own live proof. Do not reuse the upper
harvesting cell as the guide chopper position.

Exhausted-day transition: `Play-Sand.cmd --advance-day --campaign-state STATE.json
--journal CAMPAIGN.json --check` validates offline. Add `--execute
--allow-experimental` for bounded live validation. State requires day1-5,
acts_used2, settled/snapshot_current true, clear/later threat, campaign_id,
observation_id, and last_day_observation with the last observed day/image.
The end-of-day arrow hides the day number; prior owned day evidence is retained
and the next day plus two restored Acts must be observed independently. The
journal uses a separate day_transitions namespace, persists before Next Day,
and resumes without another Next Day click. This does not certify guide daily
objectives or credit food production automatically.

Native source topology review: the article's collector is logical tile5,11
(normal598,290; selected672,298), two columns west of the chopper7,11. Tile6,11
between them is unbuildable. These are candidate projected points; live green
placement, collector facing and harvested yield still need proof. The current
single-wave carrier candidate carries at most14 wood; the source24 example is
needed to preserve the later60-wood HQ2 plus14-wood hub budget if Days2/3 each
produce30 wood. Repeated carrier availability/DP handling remains unfinished.

Offline regression runs use the project's WSL `.venv/bin/python -m unittest
discover -s tools -p 'test_maa_sand*.py'`. Optional local Windows-image cases may
skip there; use the installed Windows Debug core for actual image replays/live
checks. This avoids slow Windows-to-WSL source imports during repeated unit runs.


### Live campaign follow-up, 2 November 2026

Day 3 settlements confirmed 15 wood from Jagged Jungle, followed by five
Fowlbeast Wings, one wood and one gold from Gathering of Feathers. The five
wings provide 150 base food energy. Food production multipliers and actual
crafted drink counts remain independently observed; bag estimates never
substitute for delivered settlement rewards.

The ordinary three-day score assessment appeared when advancing Day 3.
`DayTransition` recognizes the specific Day 1–3 assessment labels and journals
its acknowledgement once, then requires Day 4 with both Acts restored. This
does not claim that the guide's HQ2 prerequisite was completed.

Day 4 Water From Afar delivered 12 water for one Act and no drinks. The live
English interaction has two distinct inputs: select the option text, then
confirm its in-row Act badge. After acknowledging the Resource Gained popup,
the result narrative remained open. Select Alright and confirm its same-row
checkmark to return to the map. The floating marker above the paid option
was not a working hit target. The generic encounter handler still needs
these confirmation and popup phases; this event was completed under supervision.
Completing it revealed Within Range, which had previously been inaccessible.

Within Range now has a supervised profile with runtime anchors on I:. Its
first deployment follows the guide: Młynar north of the central trees,
facing Down. Deployment triggers a large camera pan. The entry anchor could
not register the settled view, even with the stronger Jungle matcher, so
calibration must use settled post-deployment frames. Do not loosen inlier
thresholds or count a failed post-deployment identity check as a failed
physical deployment. Recover by exact identity with `adopt_deployed`.
Autoplay stays disabled until collector positions and delivered wood are proven.

`launch_prepared(receipt)` reuses the existing gathering launch loop and the
configured screenshot backend. It requires a matching named-formation receipt,
fresh formation recognition and squad validation; an uncertain paid Start
remains pending and cannot be repeated. This avoids relying on the native
InitialPause task's failing battle-frame recognition on this emulator.

The settled world HUD still recognizes wood and gold, but water and rice can
remain unknown because their icon/counter positions or backgrounds differ.
Keep those fields unknown until calibrated; manual HUD observations must be
labeled separately. Latest regression run: 911 tests passed, with changed
Python modules passing Ruff.


The supervised Within Range expedition delivered18wood and2gold. Its bank
was independently verified across two Noir Corne loads, Beagle, Cardigan,
Młynar and Spot. Cardigan and Spot used the emptied west resource cell to
reach the next pile. These are live collector results, not a30wood completion.
The outer and inward calibration phases have different selected-card views;
the profile retains the earlier phase coordinates and provenance in history.

The edge-positioned Beagle exposed a fixed retreat-click bug. Retreat now
finds a unique red glyph on its dark control within the operator-control
region, with size, color and background checks. The observed edge control
was[690,215] instead of the old[603,233]. Its live recovery banked3wood.
If an older cooldown finishes during retreat, a positively parsed extra hand
card plus a cooling card can prove the return without requiring the net
cooling count to increase. Ambiguous returns still remain pending.

S3 carrying capacity is observed on the confirmed spent-SP panel. The live
OCR split3/3 into separate digits; the observer now reuses `carry_image` and
native OCR to preserve the slash, just as normal cargo reads already do.
No unpause is needed for this fallback. Full suite before that fallback:
927passed;52targeted carrier/skill/retreat checks passed afterward.

After the18wood settlement, a mandatory Data updated / Starting synchronization
popup returned the game through Home and daily sign-in. The owned save was
recovered and world stock reconciled at42wood,22water,12gold. Day5 was then
independently observed with both Acts available; the paid Day4 trip must not
be replayed.

`within-range-hq2-recovery-20261102` targets the missing18wood. Its opening,
chopper, outer and inner camera phases each pin their own idle/selected PNG
hashes on I:. A `phase` route step changes geometry through
`refresh_calibration(phase=...)`; it preserves cargo ownership, banked credits
and active operators. Phase records cannot change roster, skills or spending
policy, and cannot omit an occupied slot. A full route reload resets the
ledger and must never substitute for a phase change during an expedition.

The recovery profile uses the game-restored team: Młynar S3, Beagle, Spot,
Cardigan, Noir Corne and reserve Yato. Its18wood plan repeats Noir Corne and
Beagle rather than relying on Yato to carry3. It remains experimental until
18wood is independently confirmed in both the ledger and settlement. The
guide's30wood example does not establish full-rotation completion. Resource
depletion persists between Acts: the Day5 panel showed102/120wood remaining,
so review the actual field before replaying the opening collection cells.

The squad-clear helper now tolerates a delayed confirmation overlay through
four observations, while submitting Delete and Confirm at most once each.
Validation:928existing tests,27phase/launch checks and33navigation checks
passed. Runtime screenshots and journals remain on I:.


The Day5 test rejected a direct facing-selector-center identity shortcut:
after facing confirmation the camera returns to another pose, and that
pixel selected a thicket. `verify_facing_center` is disabled in the live
profile. Switching to the pinned chopper phase and exact-identity adoption
recovered the already-deployed Młynar without spending DP a second time.
The opening deployment-to-verification phase transition is still supervised.

MuMu produced a valid PNG after10.234seconds during recovery; capture now
allows12seconds, without a stale SDK-frame fallback. A Google Play Games
activity also took foreground and Arknights stopped drawing. Recovery was
performed outside battle; the owned Day5 save retained42wood/22water and
both Acts. Unsaved squad edits reverted to Yato, so old team-preparation
receipts must never substitute for a fresh exact formation check.

Native task hot reload merges retained fields. Do not change an existing
task from OCR to MatchTemplate in place. `SandPilot@SelectTalesTitle` has a
new identity and a pinned real title template: cached native positive1.0,
world negative misses. The complete resume graph remains live-unvalidated.


### Offline screenshot-built menu scripts (2026-11-02)

Eight native MAA sequences now cover Home/Terminal/theme resume, Within Range
formation, Desolate raid formation, HQ2 price inspection, saved raid preset
selection and the cooking screen. They reuse MaaCore OCR, template matching,
Custom task graphs, the existing navigator and CoreEval; no new click engine.
Actions wait for the next recognized screen. Bounded map pans and destination
guards replace repeated exploratory clicking. HQ price inspection never confirms
an upgrade; cooking never crafts; formation navigation never launches combat.

The pinned corpus contains 23 archived screenshots on I:. Native offline replay
passed **85/85 recognition checks and 8/8 complete frame sequences**. These are
recorded-screen tests, not proof of full live execution. Both replay and check
run without connecting to the emulator. The replay report pins the task bundle
and native DLL hashes; live execution rejects a stale or failed report.

From the installed `modules/sand` directory:

```bat
Screenflows-Sand.cmd --check
Screenflows-Sand.cmd --replay --output I:\MAA-data\sand-player\screenflow-recheck
```

`--execute --flow NAME --verified-report PATH` is an explicit live operation;
use it only when emulator ownership is available and the matching replay passes.
Flow names are `resume_home`, `resume_terminal`, `resume_themes`,
`within_range_formation`, `desolate_formation`, `hq2_price`, `raid_preset`, and
`open_cooking`. Every flow validates its entry and destination screens.

Formation preparation also accepts `Play-Sand.cmd --prepare-team --team-plan
pack/campaign/desolate-modern-team.json`. Without `--execute` this validates
only. It reuses CampaignTeamPreparer and exact operator recognition without
requiring combat-map anchors. Mountain/Blaze/Saria selection has not been tested
live, and this plan does not establish raid deployment coordinates.

Latest supervised campaign result supersedes the incomplete Day5 recovery
notes above: 18 wood and 3 gold settled; HQ2 upgrade spent 60 wood/5 water once.
The saved world is Day5, HQ2, one Act remaining, 0 wood/17 water/15 gold.
Desolate Interception Point is stage sandbox_1_26; its combat camera and exact
placements remain uncalibrated. The guide's Jagged Jungle placements are for a
different stage and must not be copied onto it. No raid Act was spent. Offline
work leaves that session untouched. Existing gathering phase/body coordinates
remain available, but the experimental route is not an unattended completion
claim. Next live test should validate one prepared menu sequence, then pause
raid entry for camera calibration before spending deployment DP.


### MAA task queue

The local GUI now exposes Reclamation Algorithm in Add Task. Its default
Resume Sand save operation loads this packaged resource overlay through the
GUI's own core and runs the existing guarded menu graphs. It stops at the world
map, spends no Act, and supports the English client. Native prosperity farming
in an existing save is a separate mode with persisted tool/batch/store settings.
The task is disabled until selected; Select All excludes it. The separate Python
player remains the implementation for supervised campaign calibration. Queued
resume does not claim automatic Day1–6 combat, and does not create/reset a save.

Restored queue entries include QueueVersion=2. This distinguishes them from old Reclamation entries that upstream migrates into Toolbox; deleting that marker from portable settings invokes the legacy migration.
