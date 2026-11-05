#include "RoguelikeStageReadinessTaskPlugin.h"
#include "JieGardenStageReadiness.h"
#include "JieGardenStrategy.h"

#include "Config/Miscellaneous/TilePack.h"
#include "Controller/Controller.h"
#include "Task/ProcessTask.h"
#include "Utils/DebugImageHelper.hpp"
#include "Utils/Logger.hpp"
#include "Vision/Matcher.h"
#include "Vision/MultiMatcher.h"
#include "Vision/OCRer.h"

bool asst::RoguelikeStageReadinessTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }
    const auto task = details.get("details", "task", std::string());
    if (msg == AsstMsg::SubTaskStart && task.ends_with("Roguelike@StrategyChange")) {
        const auto strategy = details.get("details", "result", "text", std::string());
        m_restricted = strategy.find("boskyPassage") != std::string::npos;
        return false;
    }
    if (msg == AsstMsg::SubTaskCompleted &&
        (task == "JieGarden@Roguelike@StageCombatOps" || task == "JieGarden@Roguelike@StageEmergencyOps")) {
        m_source_task = task;
        m_entry_check = false;
        return true;
    }
    if (msg == AsstMsg::SubTaskStart &&
        (task == "JieGarden@Roguelike@StageCombatOpsEnter" || task == "JieGarden@Roguelike@StageEmergencyOpsEnter")) {
        m_source_task = task;
        m_entry_check = true;
        return true;
    }
    return false;
}

void asst::RoguelikeStageReadinessTaskPlugin::reset_in_run_variables()
{
    m_restricted = false;
    m_entry_check = false;
    m_allow_forced_entry = false;
    if (auto* process = dynamic_cast<ProcessTask*>(m_task_ptr)) {
        process->remove_override_next("JieGarden@Roguelike@StageCombatOps");
        process->remove_override_next("JieGarden@Roguelike@StageEmergencyOps");
    }
    m_source_task.clear();
    m_avoided_stage.clear();
}

std::string asst::RoguelikeStageReadinessTaskPlugin::preview_stage_name(const cv::Mat& image) const
{
    if (image.empty()) {
        return {};
    }
    OCRer name(image);
    name.set_task_info("JieGarden@Roguelike@ReadinessGuardPreviewName");
    if (!name.analyze()) {
        return {};
    }
    for (const auto& recognized : name.get_result()) {
        if (recognized.score < 0.8) {
            continue;
        }
        TilePack::LevelKey key;
        key.name = recognized.text;
        // Unknown or partial titles never authorize committing a different stage.
        if (Tile.find(key)) {
            return recognized.text;
        }
    }
    return {};
}

bool asst::RoguelikeStageReadinessTaskPlugin::normal_entry_available(const cv::Mat& image) const
{
    if (image.empty()) {
        return false;
    }
    Matcher entry(image);
    entry.set_task_info("JieGarden@Roguelike@StageCombatOpsEnter");
    return entry.analyze().has_value();
}

void asst::RoguelikeStageReadinessTaskPlugin::report(
    const std::string& decision,
    const std::string& selected,
    const JieGardenTeam& team)
{
    LogInfo << "Sui stage readiness: " << decision << " selected " << selected << " stable healers " << team.healers
            << " E2 carries " << team.elite2_carries;
    auto info = basic_info_with_what("SuiStageReadinessGuard");
    info["details"] = json::object {
        { "decision", decision },
        { "stage", m_avoided_stage },
        { "selected_stage", selected },
        { "stable_healers", team.healers },
        { "elite2_carries", team.elite2_carries },
    };
    callback(AsstMsg::SubTaskExtraInfo, info);
}

bool asst::RoguelikeStageReadinessTaskPlugin::_run()
{
    auto* process = dynamic_cast<ProcessTask*>(m_task_ptr);
    if (!process) {
        return false;
    }
    process->remove_override_next(m_source_task);
    const bool forced_entry = m_entry_check && m_allow_forced_entry;
    m_allow_forced_entry = false;
    const auto team = jiegarden_team(*m_config);
    // Bosky passages use a separate map navigator and a restricted roster.
    if (m_restricted || !m_config->jiegarden_strategy().cautious_routing) {
        return true;
    }
    const auto initial_preview = ctrler()->get_image();
    const auto avoided_stage = preview_stage_name(initial_preview);
    const auto should_avoid = [&](const std::string& stage) {
        return avoid_jiegarden_stage(stage, team, m_config->get_difficulty(), true);
    };
    if (!should_avoid(avoided_stage)) {
        return true;
    }
    m_avoided_stage = avoided_stage;
    if (m_entry_check) {
        if (forced_entry) {
            report("forced_route_entry", avoided_stage, team);
        }
        else {
            // A resumed preview has no verified sibling scan. Keep the map open for a new choice.
            report("stopped_unchecked_preview", avoided_stage, team);
            process->set_enable(false);
        }
        return true;
    }
    const auto hit = process->get_last_hit();
    const auto map_image = get_hit_image();
    if (!hit || !map_image) {
        m_allow_forced_entry = true;
        report("forced_no_map_evidence", avoided_stage, team);
        return true;
    }
    const auto original = hit->rect;
    MultiMatcher nodes(*map_image);
    nodes.set_task_info("JieGarden@Roguelike@StageCombatOps");
    if (!nodes.analyze()) {
        m_allow_forced_entry = true;
        report("forced_no_sibling", avoided_stage, team);
        return true;
    }
    auto candidates = nodes.get_result();
    sort_by_vertical_(candidates);
    int inspected = 0;
    for (const auto& candidate : candidates) {
        if (!jiegarden_sibling_candidate(original, candidate.rect)) {
            continue;
        }
        if (need_exit() || ++inspected > 8) {
            break;
        }
        ctrler()->click(
            Point(candidate.rect.x + candidate.rect.width / 2, candidate.rect.y + candidate.rect.height / 2));
        if (!sleep(600)) {
            break;
        }
        const auto preview = ctrler()->get_image();
        const auto name = preview_stage_name(preview);
        if (name.empty() || should_avoid(name) || !normal_entry_available(preview)) {
            continue;
        }
        if (!process->override_next(m_source_task, { "JieGarden@Roguelike@ReadinessGuardContinue" })) {
            process->set_enable(false);
            return true;
        }
        report("alternate", name, team);
        utils::save_debug_image(
            preview,
            utils::path("debug") / "roguelike" / "readiness",
            true,
            "Sui readiness alternate",
            "alternate");
        return true;
    }
    if (need_exit()) {
        return true;
    }
    if (inspected == 0) {
        m_allow_forced_entry = true;
        report("forced_no_sibling", avoided_stage, team);
        return true;
    }
    // Preserve a forced route, but never commit an unverified last preview.
    ctrler()->click(Point(original.x + original.width / 2, original.y + original.height / 2));
    if (sleep(600) && preview_stage_name(ctrler()->get_image()) == avoided_stage) {
        m_allow_forced_entry = true;
        report("forced_no_verified_alternative", avoided_stage, team);
        return true;
    }
    report("stopped_preview_restore_failed", "", team);
    process->set_enable(false);
    return true;
}
