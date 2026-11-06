"""Bounded HQ1-to-HQ2 progression using existing native controls and durable journals."""

from maa_runtime import data_path

import copy
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from maa_sand_config import CheckpointError
from maa_sand_days import ActJournal
from maa_sand_settlement import enlarged_count, text_key
from maa_sand_world import read_world

COSTS = {"wood": 60, "water": 5}


def review_hq2(state):
    for key, low, high in (
        ("day", 1, 6),
        ("acts_used", 0, 2),
        ("hq", 1, 10),
        ("wood", 0, 999999),
        ("water", 0, 999999),
    ):
        if type(state.get(key)) is not int or not low <= state[key] <= high:
            raise CheckpointError("HQ upgrade requires an observed integer: " + key)
    blockers = []
    if state.get("snapshot_current") is not True or state.get("settled") is not True:
        blockers.append("Require a current settled campaign observation")
    if state["hq"] != 1:
        blockers.append(
            "Only HQ1 to HQ2 is supported; never repeat or upgrade a higher level"
        )
    if state.get("threat") not in ("clear", "later"):
        blockers.append(
            "Resolve unknown or urgent raid timing before construction spending"
        )
    for key in ("campaign_id", "observation_id"):
        if not isinstance(state.get(key), str) or not state[key].strip():
            blockers.append("Require explicit " + key)
    deficit = {name: max(0, cost - state[name]) for name, cost in COSTS.items()}
    if any(deficit.values()):
        blockers.append("Observe the complete wood60/water5 budget before navigation")
    return {
        "activity": "hq1-to-hq2",
        "blockers": blockers,
        "cost_reference": dict(COSTS),
        "deficit": deficit,
        "live_cost_confirmation_required": True,
        "autoplay_enabled": False,
        "game_connected": False,
        "day_advance_enabled": False,
        "automatic_inventory_credit": False,
    }


def one_integer(reads):
    if (
        len(reads) != 1
        or reads[0].get("score", 0) < 0.85
        or re.fullmatch(r"\s*\d{1,2}\s*", reads[0].get("text", "")) is None
    ):
        raise CheckpointError("HQ level/day needs one exact confident integer")
    return int(reads[0]["text"])


def read_hq_details(runtime, path):
    hits = runtime.matches(path, ["SandAuto@HQDetails"])
    if hits.get("SandAuto@HQDetails", {}).get("score", 0) < 0.85:
        raise CheckpointError("English Headquarters details are not identified")
    # The world HUD owns HQ level proof; the large camp-overlaid digit is not reliable OCR.
    roi = [1154, 70, 45, 45]
    reads = runtime.ocr(path, roi)
    prepared = None
    try:
        day = one_integer(reads)
    except CheckpointError:
        prepared, large = enlarged_count(path, roi)
        reads = runtime.ocr(prepared, large)
        day = one_integer(reads)
    return {
        "image": str(path),
        "day": day,
        "day_reads": reads,
        "prepared_image": str(prepared) if prepared else None,
        "evidence": hits,
    }


def material_ratio(reads, cost):
    if len(reads) != 1 or reads[0].get("score", 0) < 0.85:
        raise CheckpointError("HQ material ratio requires one confident native reading")
    match = re.fullmatch(r"\s*(\d{1,6})\s*/\s*(\d{1,3})\s*", reads[0].get("text", ""))
    if match is None or int(match[2]) != cost:
        raise CheckpointError(
            "HQ material owned/cost ratio differs from the exact upgrade price"
        )
    return int(match[1])


def read_hq_upgrade(runtime, path):
    tasks = [
        "SandAuto@HQUpgradePanel",
        "SandAuto@HQUpgradeTarget2",
        "SandAuto@HQConfirmUpgrade",
        "SandAuto@HQUpgradeWood",
        "SandAuto@HQUpgradeWater",
    ]
    hits = runtime.matches(path, tasks)
    if any(
        hits.get(task, {}).get("score", 0)
        < (0.95 if task.endswith(("Wood", "Water")) else 0.85)
        for task in tasks
    ):
        raise CheckpointError(
            "Exact English HQ2 upgrade panel, materials and control are required"
        )
    reads = runtime.ocr(path, [788, 465, 240, 40])
    if len(reads) != 1 or reads[0].get("score", 0) < 0.85:
        raise CheckpointError("Survival requirement is unreadable")
    survival = re.fullmatch(
        r"\s*Survive\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)\s*days\s*",
        reads[0].get("text", ""),
        re.IGNORECASE,
    )
    if survival is None or int(survival[2]) != 1:
        raise CheckpointError(
            "HQ2 survival requirement must be actually observed as one day"
        )
    materials = read_hq_materials(runtime, path, hits)
    return {
        **materials,
        "target_level": 2,
        "panel_verified": True,
        "survival_met": int(survival[1]) >= 1,
        "survival_reads": reads,
    }


def read_hq_materials(runtime, path, hits=None):
    """Component proof only; never authorizes an upgrade without the English panel guard."""
    hits = (
        hits
        if hits is not None
        else runtime.matches(
            path, ["SandAuto@HQUpgradeWood", "SandAuto@HQUpgradeWater"]
        )
    )
    if any(
        hits.get("SandAuto@HQUpgrade" + name.title(), {}).get("score", 0) < 0.95
        for name in COSTS
    ):
        raise CheckpointError("Both HQ upgrade material identities are required")
    owned = {}
    evidence = {}
    for name, cost in COSTS.items():
        icon = hits["SandAuto@HQUpgrade" + name.title()]
        rect = icon.get("rect", [])
        if (
            len(rect) != 4
            or any(type(v) is not int for v in rect)
            or rect[2:] != [40, 36]
            or not (740 <= rect[0] <= 960 and 510 <= rect[1] <= 554)
        ):
            raise CheckpointError("HQ material icon has no reviewed native position")
        template = icon.get("templ")
        original = "SandHQUpgrade" + name.title() + ".png"
        funded = "SandHQUpgrade" + name.title() + "Funded.png"
        if template not in (original, funded):
            raise CheckpointError("HQ material template variant is unreviewed")
        x, y, _w, _h = rect
        roi = (
            [x - 2, y + 35, 80, 27] if template == funded else [x + 17, y + 35, 58, 27]
        )
        quantity = runtime.ocr(path, roi)
        prepared = None
        try:
            count = material_ratio(quantity, cost)
        except CheckpointError:
            prepared, large = enlarged_count(path, roi)
            quantity = runtime.ocr(prepared, large)
            count = material_ratio(quantity, cost)
        owned[name] = count
        evidence[name] = {
            "icon": icon,
            "roi": roi,
            "quantity_reads": quantity,
            "prepared_image": str(prepared) if prepared else None,
        }
    if evidence["wood"]["icon"]["rect"][0] + 40 > evidence["water"]["icon"]["rect"][0]:
        raise CheckpointError("HQ materials must occupy distinct ordered icon slots")
    return {
        "image": str(path),
        "costs": dict(COSTS),
        "owned": owned,
        "evidence": evidence,
        "funded": all(owned[key] >= cost for key, cost in COSTS.items()),
        "panel_verified": False,
        "inventory_updated": False,
    }


def success_ready(runtime, path, hits):
    if hits.get("SandAuto@HQSuccessCheck", {}).get("score", 0) < 0.95:
        return False
    titles = runtime.ocr(path, [530, 420, 230, 45])
    if not any(
        row.get("score", 0) >= 0.85 and text_key(row.get("text", "")) == "headquarters"
        for row in titles
    ):
        return False
    return one_integer(runtime.ocr(path, [580, 300, 120, 90])) == 2


def verify_before(state, before):
    if (
        before.get("hq") != 1
        or before.get("acts_remaining") != 2 - state["acts_used"]
        or (
            before.get("day") != state["day"]
            and not (before.get("day") is None and state["acts_used"] == 2)
        )
    ):
        raise CheckpointError(
            "Fresh world HQ/day/Acts differ from the construction observation"
        )
    if any(before.get("resources", {}).get(name) != state[name] for name in COSTS):
        raise CheckpointError(
            "Fresh construction materials differ from the observed budget"
        )


def verify_after(state, before, after):
    if not after.get("image") or after["image"] == before["image"]:
        raise CheckpointError("HQ upgrade requires a new world observation")
    if (
        after.get("hq") != 2
        or after.get("acts_remaining") != before["acts_remaining"]
        or (
            after.get("day") != state["day"]
            and not (after.get("day") is None and state["acts_used"] == 2)
        )
    ):
        raise CheckpointError("HQ upgrade must show HQ2 without a day or Act change")
    for name, old in before["resources"].items():
        new = after["resources"].get(name)
        if name in COSTS:
            if type(old) is not int or type(new) is not int or new != old - COSTS[name]:
                raise CheckpointError(
                    "HQ upgrade resource debit differs from its exact confirmed price"
                )
        elif old is not None and new != old:
            raise CheckpointError(
                "Unrelated resources changed during the owned HQ upgrade"
            )
    return {
        "hq2_verified": True,
        "act_consumed": False,
        "day_advanced": False,
        "inventory_updated": False,
        "observed_costs": dict(COSTS),
    }


def observe_construction(runtime, label, extra=()):
    path, _ = runtime.capture(label)
    tasks = [
        "SandAuto@World",
        "SandAuto@HQDetails",
        "SandAuto@HQUpgradePanel",
        "SandAuto@HQSuccessCheck",
        "SandAuto@Battle",
        "SandAuto@RaidBattle",
        "SandAuto@Paused",
        *extra,
    ]
    hits = runtime.matches(path, tasks)
    if any(key in hits for key in ("SandAuto@Battle", "SandAuto@RaidBattle")):
        if "SandAuto@Paused" not in hits:
            runtime.task("SandPilot@PauseNavigationBattle")
            paused, _ = runtime.capture("hq-unexpected-battle-paused")
            if not runtime.matches(paused, ["SandAuto@Paused"]):
                raise CheckpointError("Unexpected battle pause unconfirmed")
        raise CheckpointError("Unexpected battle preserved paused; HQ upgrade stopped")
    return path, hits


class HeadquartersUpgrade:
    def __init__(self, runtime, journal_path, campaign_id):
        self.rt = runtime
        self.journal = ActJournal(journal_path, campaign_id + ":hq2")

    def observe(self, label):
        return observe_construction(self.rt, label)

    def wait(self, label, expected):
        # Await the destination after a click; never resend the action while its
        # animation or server response is still pending.
        for attempt in range(6):
            path, hits = self.observe(label)
            if expected in hits:
                return path, hits
            if attempt < 5:
                time.sleep(0.25)
        raise CheckpointError("HQ navigation destination not confirmed: " + expected)

    def run(self, state):
        review = review_hq2(state)
        if review["blockers"]:
            raise CheckpointError("; ".join(review["blockers"]))
        if self.journal.campaign_id != state["campaign_id"] + ":hq2":
            raise CheckpointError("Construction journal belongs to another campaign")
        with self.journal.locked() as journal:
            if journal.data["acts"]:
                raise CheckpointError(
                    "HQ upgrade already pending or verified; never repeat it"
                )
            path, hits = self.observe("hq-world-before")
            if "SandAuto@World" not in hits:
                raise CheckpointError("Start HQ upgrade from the actual world map")
            before = read_world(self.rt, path)
            verify_before(state, before)
            entry = {
                "status": "pending",
                "before": before,
                "observation_id": state["observation_id"],
                "submitted": False,
                "inventory_updated": False,
            }
            journal.data["acts"]["hq2"] = entry
            journal.save()
            try:
                self.rt.task("SandPilot@Headquarters")
                path, _ = self.wait("hq-details-before", "SandAuto@HQDetails")
                details = read_hq_details(self.rt, path)
                if details["day"] != state["day"]:
                    raise CheckpointError(
                        "HQ calendar must agree before opening the upgrade"
                    )
                entry["details_before"] = details
                journal.save()
                self.rt.task("SandPilot@HQOpenUpgrade")
                path, _ = self.wait("hq-upgrade-price", "SandAuto@HQUpgradePanel")
                price = read_hq_upgrade(self.rt, path)
                entry["price"] = price
                journal.save()
                if (
                    price.get("panel_verified") is not True
                    or price["costs"] != COSTS
                    or not price["funded"]
                    or not price["survival_met"]
                    or price["owned"] != {key: state[key] for key in COSTS}
                ):
                    raise CheckpointError(
                        "Actual complete HQ budget or survival condition is not confirmed"
                    )
                entry["submitted"] = True
                journal.save()
                self.rt.task("SandPilot@HQConfirmUpgrade")
                details_verified = False
                for _ in range(20):
                    path, hits = self.observe("hq-upgrade-transition")
                    if success_ready(self.rt, path, hits):
                        if entry.get("success_ack_submitted"):
                            raise CheckpointError(
                                "HQ success acknowledgement unresolved; never repeat it"
                            )
                        entry["success_ack_submitted"] = True
                        entry["success_image"] = str(path)
                        journal.save()
                        self.rt.task("SandPilot@HQSuccessCheck")
                    elif "SandAuto@HQDetails" in hits:
                        details = read_hq_details(self.rt, path)
                        if details["day"] != state["day"]:
                            raise CheckpointError(
                                "Post-upgrade HQ calendar verification failed"
                            )
                        if entry.get("details_back_submitted"):
                            raise CheckpointError(
                                "HQ details return unresolved; never repeat it"
                            )
                        details_verified = True
                        entry.update(details_after=details, details_back_submitted=True)
                        journal.save()
                        self.rt.task("SandPilot@Back")
                    elif "SandAuto@World" in hits:
                        after = read_world(self.rt, path)
                        if details_verified:
                            facts = verify_after(state, before, after)
                            entry.update(
                                status="verified", after=after, verification=facts
                            )
                            journal.save()
                            return copy.deepcopy(entry)
                        if entry.get("post_details_open_submitted"):
                            raise CheckpointError(
                                "Post-upgrade details navigation unresolved"
                            )
                        entry["post_details_open_submitted"] = True
                        journal.save()
                        self.rt.task("SandPilot@Headquarters")
                    elif "SandAuto@HQUpgradePanel" in hits:
                        if entry.get("panel_return_submitted"):
                            raise CheckpointError(
                                "Post-upgrade panel return unresolved; never repeat it"
                            )
                        entry["panel_return_submitted"] = True
                        journal.save()
                        self.rt.task("SandPilot@HQUpgradeReturn")
                    time.sleep(0.5)
                raise CheckpointError(
                    "HQ upgrade transition unconfirmed; never repeat the paid action"
                )
            except BaseException as exc:
                entry["error"] = str(exc)
                journal.save()
                try:
                    self.observe("hq-stopped")
                except Exception as checkpoint_error:  # noqa: BLE001 - preserve the original construction failure
                    self.rt.log("hq_stop_checkpoint", reason=str(checkpoint_error))
                raise


def run_construction_cli(
    args,
    parser,
    runtime_factory,
    reviewer,
    workflow,
    flag,
    suffix,
    folder,
    event_name=None,
):
    if (
        any(
            (
                args.route,
                args.raid_profile,
                args.raid_run_id,
                args.campaign_act,
                args.visit_liaison,
                args.assets,
            )
        )
        or args.campaign_state is None
    ):
        parser.error(
            flag
            + " requires --campaign-state and cannot combine battle/visit modes or camera assets"
        )
    try:
        state = json.loads(args.campaign_state.read_text(encoding="utf-8-sig"))
        review = reviewer(state)
        if args.check or not args.execute:
            print(json.dumps(review, indent=2))
            return
        if not args.allow_experimental or args.journal is None:
            raise CheckpointError(
                "Construction execution requires --allow-experimental and --journal"
            )
        if review["blockers"]:
            raise CheckpointError("; ".join(review["blockers"]))
        output = args.output or data_path("sand-player") / folder / datetime.now(
            UTC
        ).strftime("%Y%m%dT%H%M%SZ")
    except (CheckpointError, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    with runtime_factory(args.runtime, output, args.pack) as runtime:
        journal = args.journal.with_name(args.journal.name + suffix)
        result = workflow(runtime, journal, state["campaign_id"]).run(state)
        runtime.log(event_name or folder.replace("-", "_") + "_result", **result)


def run_hq_cli(args, parser, runtime_factory):
    return run_construction_cli(
        args,
        parser,
        runtime_factory,
        review_hq2,
        HeadquartersUpgrade,
        "--upgrade-hq2",
        ".hq2",
        "hq-upgrade",
        event_name="headquarters_upgrade_result",
    )
