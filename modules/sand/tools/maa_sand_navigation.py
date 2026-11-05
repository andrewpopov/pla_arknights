"""Named campaign formation navigation; does not start battles or select quantities."""

import json
import time
from pathlib import Path

from maa_sand_battle import guard_unidentified_battle
from maa_sand_config import CheckpointError, default_pack


class CampaignNavigator:
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        self.pack = Path(pack) if pack else default_pack()
        catalog = json.loads(
            (self.pack / "campaign/stages.json").read_text(encoding="utf8")
        )
        if catalog.get("schema_version") != 1 or catalog.get("theme") != "Tales":
            raise CheckpointError("Unsupported campaign navigation catalog")
        self.stages = catalog["stages"]
        self.clear_pending = False

    @staticmethod
    def hit(hits, task):
        return hits.get(task, {}).get("score", 0) >= 0.85

    def frame(self, label, extras=()):
        path, _ = self.rt.capture(label)
        tasks = [
            "SandAuto@World",
            "SandAuto@Squad",
            "SandAuto@Battle",
            "SandAuto@RaidBattle",
            "SandAuto@Paused",
            "BattleOfficiallyBegin",
            *extras,
        ]
        hits = self.rt.matches(path, tasks)
        guard_unidentified_battle(self.rt, path, hits)
        if any(t in hits for t in ("SandAuto@Battle", "SandAuto@RaidBattle")):
            if "SandAuto@Paused" not in hits:
                self.rt.task("SandPilot@PauseNavigationBattle")
                path, _ = self.rt.capture("navigation-battle-pause")
                if not self.rt.matches(path, ["SandAuto@Paused"]):
                    raise CheckpointError("Unexpected battle; pause was not confirmed")
            raise CheckpointError(
                "Battle preserved paused; formation navigation stopped"
            )
        return path, hits

    def prepare_formation(self, stage_id, *, before_formation=None):
        stage = self.stages.get(stage_id)
        if stage is None:
            raise CheckpointError(
                "Stage is outside the reviewed early campaign catalog"
            )
        suffix = stage["observer"].split("@Stage", 1)[1]
        detail = "SandAuto@Details" + suffix
        node = "SandPilot@Node" + suffix
        extras = [detail, node]
        path, hits = self.frame("campaign-navigation-entry", extras)
        if self.hit(hits, "SandAuto@Squad"):
            self.rt.task("SandPilot@Back")
            path, hits = self.frame("campaign-navigation-world", extras)
        outpost_detail = stage.get("kind") == "outpost" and self.hit(hits, detail)
        if not self.hit(hits, "SandAuto@World") and not outpost_detail:
            raise CheckpointError("Named formation navigation requires the world map")
        if not self.hit(hits, detail):
            if not self.hit(hits, node):
                # Reuse native named-node recognition after each bounded world pan.
                # Gestures only move the camera; no unrecognized marker is clicked.
                gestures = (((650, 220), (650, 430)), ((650, 430), (650, 150)))
                if stage.get("kind") != "outpost":
                    gestures = (
                        ((420, 330), (900, 330)),
                        ((420, 330), (900, 330)),
                        ((900, 330), (420, 330)),
                        ((900, 330), (420, 330)),
                        ((650, 220), (650, 430)),
                        ((650, 430), (650, 150)),
                    )
                for start, end in gestures:
                    self.rt.swipe(start, end)
                    path, hits = self.frame("campaign-node-search", extras)
                    if not self.hit(hits, "SandAuto@World"):
                        raise CheckpointError(
                            "Node search left the world map; no node input submitted"
                        )
                    if self.hit(hits, node):
                        break
                else:
                    raise CheckpointError(
                        "Named marker remains hidden; no node or battle Start submitted"
                    )
            self.rt.task(node)
            for attempt in range(4):
                path, hits = self.frame("campaign-node-details", [detail])
                if self.hit(hits, detail):
                    break
                if attempt < 3:
                    time.sleep(0.25)
        # Outpost sidebars replace the world HQ control; their exact stage title
        # is the destination proof. Resource sidebars retain the world control.
        if not self.hit(hits, detail) or (
            stage.get("kind") != "outpost" and not self.hit(hits, "SandAuto@World")
        ):
            raise CheckpointError(
                "Requested stage details were not confirmed; do not enter another stage"
            )
        selected = str(path)
        if before_formation is not None:
            before_formation(path, stage_id)
        # Native chain rechecks this exact detail title before clicking its Start control.
        self.rt.task("SandPilot@Formation" + suffix)
        for _ in range(8):
            path, hits = self.frame("campaign-formation")
            if self.hit(hits, "SandAuto@Squad"):
                result = {
                    "status": "named_formation_prepared",
                    "stage_id": stage_id,
                    "stage": stage["english"],
                    "details_image": selected,
                    "formation_image": str(path),
                    "tool_contents_verified": False,
                    "squad_verified": False,
                    "battle_started": False,
                }
                self.rt.log("campaign_formation_prepared", **result)
                return result
            time.sleep(0.25)
        raise CheckpointError("Named stage did not return a formation screen")

    def prepare_next(self, state, *, request_tools=True):
        from maa_sand_campaign import advise, load_campaign

        advice = advise(state, load_campaign(self.pack))
        if (
            not state["snapshot_current"]
            or not state["settled"]
            or state["threat"] == "unknown"
        ):
            raise CheckpointError(
                "Campaign formation requires current settled state and known threat timing"
            )
        step = advice["next"]
        if step is None:
            raise CheckpointError("Daily Acts are spent; no automatic day advance")
        if step["stage_id"] is None:
            raise CheckpointError(
                "Next Act requires an observed raid/event handler, not named formation navigation"
            )
        result = self.prepare_formation(step["stage_id"])
        result["campaign"] = {
            "day": step["day"],
            "act": step["act"],
            "required_tools": step["required_tools"],
        }
        if request_tools and step["required_tools"]:
            result["tools_checkpoint"] = self.request_tools_tab()
        return result

    def request_tools_tab(self):
        path, hits = self.frame("formation-tools-before")
        if not self.hit(hits, "SandAuto@Squad"):
            raise CheckpointError("Tools tab requires an identified English formation")
        self.rt.task("SandPilot@FormationToolsTab")
        path, hits = self.frame("formation-tools-checkpoint")
        if not self.hit(hits, "SandAuto@Squad"):
            raise CheckpointError("Formation was not preserved after Tools tab request")
        return {
            "status": "tools_tab_requested",
            "image": str(path),
            "tool_contents_verified": False,
            "battle_started": False,
        }

    def prepare_empty_next(self, state):
        """Prepare the guide's empty squad, without starting or equipping tools."""
        from maa_sand_campaign import advise, load_campaign

        advice = advise(state, load_campaign(self.pack))
        step = advice["next"]
        if (
            not state["snapshot_current"]
            or not state["settled"]
            or state["threat"] not in ("clear", "later")
            or step is None
            or not step["empty_squad_supported"]
            or step["stage_id"] is None
        ):
            raise CheckpointError(
                "Empty squad is only supported for the current reviewed empty-squad trip"
            )
        if self.clear_pending:
            raise CheckpointError(
                "Previous squad clear is unresolved; do not submit another clear"
            )
        result = self.prepare_formation(step["stage_id"])
        result["empty_squad"] = self.clear_squad()
        result["squad_verified"] = True
        result["tool_contents_verified"] = False
        result["required_tools"] = step["required_tools"]
        return result

    def clear_squad(self):
        """Use native clear once, confirm once, then require all seven empty labels."""
        if self.clear_pending:
            raise CheckpointError("Previous squad clear is unresolved; do not retry")
        empty = [f"SandAuto@EmptySquadSlot{i}" for i in range(1, 8)]
        extras = [*empty, "SandAuto@ClearSquad", "SandAuto@ClearSquadConfirm"]
        path, hits = self.frame("empty-squad-before", extras)
        if not self.hit(hits, "SandAuto@Squad"):
            raise CheckpointError(
                "Squad clear requires an identified English formation"
            )
        if self.hit(hits, "SandAuto@ClearSquadConfirm"):
            raise CheckpointError("Unowned confirmation is open; squad clear stopped")
        if not all(self.hit(hits, task) for task in empty):
            if not self.hit(hits, "SandAuto@ClearSquad"):
                raise CheckpointError("Native clear-squad control was not recognized")
            # The native Delete control clears the loadout; tools must be rechecked later.
            self.clear_pending = True
            self.rt.task("SandPilot@ClearSquad")
            # The delete button can return before the confirmation overlay is drawn.
            # Observe a bounded transition; do not repeat the loadout reset.
            for attempt in range(4):
                path, hits = self.frame("empty-squad-confirm", extras)
                if self.hit(hits, "SandAuto@ClearSquadConfirm"):
                    break
                if attempt < 3:
                    time.sleep(0.25)
            else:
                raise CheckpointError(
                    "Squad clear confirmation was not observed; submission remains pending"
                )
            self.rt.task("SandPilot@ClearSquadConfirm")
            for _ in range(8):
                path, hits = self.frame("empty-squad-after", extras)
                if (
                    self.hit(hits, "SandAuto@Squad")
                    and not self.hit(hits, "SandAuto@ClearSquadConfirm")
                    and all(self.hit(hits, task) for task in empty)
                ):
                    self.clear_pending = False
                    break
                time.sleep(0.25)
            else:
                raise CheckpointError(
                    "All empty operator slots were not confirmed; clear remains pending"
                )
        result = {
            "status": "empty_squad_verified",
            "image": str(path),
            "operator_count": 0,
            "tool_contents_verified": False,
            "battle_started": False,
            "drinks_still_required": 2,
        }
        self.rt.log("campaign_empty_squad_prepared", **result)
        return result
