# Daily tasks, resources and IS

## One controller at a time

Use the WPF task queue for normal operation. Stop it before running optional native research controllers. Do not let another automation or a second MAA instance control the same emulator. Exit through the tray menu before replacing a build.

## Daily tasks

Configure Base, Recruitment, Credit Store and Rewards individually before running the whole queue. A loading-screen wait is different from a task being completed: inspect the task result and the game's final screen. The fork adds bounded loading recovery for recruitment/friend visits and recognition adjustments; a timeout still needs a fresh log and screenshot review.

## Combat resource stocks

Add the native Depot Maintenance task before Combat, with Tier 3 material plan targets of 10 each. Then configure Combat with CE-6 (LMD) and LS-6 (EXP) as optional fallback stages. Verify selected stages and stage availability. The maintenance task scans inventory and farms shortages before the fallback Combat task. Review any sanity potion or premium currency settings before starting; install does not grant a spending budget or import the old PC's inventory.

The optional `tools/maintenance/configure_resource_stock.py` helper can rank permanent English-server stages using a separately supplied Penguin Statistics matrix and availability snapshot, prepare a policy, and apply it while MAA is fully closed. It defaults to preparation only; run `--help` for required inputs. No stale statistics snapshot is shipped.

Inventory-based farming needs a successful current depot/inventory scan. Check the app's stock result before trusting a target. The actual operator promotion plan can require more than the healthy-stock minimum.

## Integrated Strategies

Select the theme and a difficulty that is unlocked on the account. The fork includes IS6 route/readiness checks, recruitment and voucher-conservation policies, Tongbao handling, authored deployments, facing/redeployment safeguards and recovery logic. These improve decisions but do not guarantee clears at every squad strength.

Raidian's Elite 2 and summon deployment-slot upgrade matter; do not assume an early unpromoted Raidian has the same carrying power. Damage and sustainable lane holding must come online before repeated defensive summons consume the DP budget. Review healer reach and deployment facing on a new squad.

For failure review, retain the latest log segment and battle/result screenshots, identify the stage and life lost, then compare recruitment, power level, deployment order, facing and timing. Review Tongbao effects and route choices as well as the last battle. Avoid replaying a difficult map repeatedly without enough squad power.

Use the app's exposed options; internal task JSON and research prototypes are not all GUI switches. Change one strategy at a time and retain an outcome record.
