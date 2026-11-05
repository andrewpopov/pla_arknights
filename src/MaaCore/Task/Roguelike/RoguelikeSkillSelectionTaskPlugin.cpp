#include "RoguelikeSkillSelectionTaskPlugin.h"

#include "Config/Roguelike/RoguelikeRecruitConfig.h"
#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "JieGarden/JieGardenBattleSafety.h"
#include "Utils/Logger.hpp"
#include "Vision/OCRer.h"
#include "Vision/Roguelike/RoguelikeSkillSelectionImageAnalyzer.h"

bool asst::RoguelikeSkillSelectionTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (msg != AsstMsg::SubTaskStart || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }

    if (!RoguelikeConfig::is_valid_theme(m_config->get_theme())) {
        Log.error("Roguelike name doesn't exist!");
        return false;
    }
    const std::string roguelike_name = m_config->get_theme() + "@";
    const std::string& task = details.get("details", "task", "");
    std::string_view task_view = task;
    if (task_view.starts_with(roguelike_name)) {
        task_view.remove_prefix(roguelike_name.length());
    }
    m_read_preview =
        m_config->get_theme() == RoguelikeTheme::JieGarden &&
        (task_view == "Roguelike@StageCombatOpsEnter" || task_view == "Roguelike@StageEmergencyOpsEnter" ||
         task_view == "Roguelike@StageDreadfulFoeEnter" || task_view == "Roguelike@StageDreadfulFoe-5Enter");
    if (m_read_preview || task_view == "Roguelike@StartAction") {
        return true;
    }
    else {
        return false;
    }
}

bool asst::RoguelikeSkillSelectionTaskPlugin::_run()
{
    LogTraceFunction;

    auto image = ctrler()->get_image();
    if (m_read_preview) {
        m_config->status().selected_skills.clear();
        m_prebattle_stage.clear();
        OCRer preview(image);
        preview.set_task_info("JieGarden@Roguelike@ReadinessGuardPreviewName");
        if (preview.analyze()) {
            for (const auto& result : preview.get_result()) {
                if (result.score >= 0.9 && result.text == "破岁阵祀") {
                    m_prebattle_stage = result.text;
                    LogInfo << "Sui skill policy recognized final-boss preview " << result.text;
                    break;
                }
            }
        }
        return true;
    }
    m_config->status().selected_skills.clear();
    RoguelikeSkillSelectionImageAnalyzer analyzer(image);

    if (!analyzer.analyze()) {
        return false;
    }

    int delay = Task.get("RoguelikeSkillSelectionMove1")->post_delay;
    bool has_rookie = false;
    for (const auto& [name, skill_vec] : analyzer.get_result()) {
        const auto& oper_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), name);
        if (oper_info.name.empty()) {
            Log.warn("Unknown oper", name);
            continue;
        }

        if (oper_info.alternate_skill > 0) {
            Log.info(__FUNCTION__, name, " select alternate skill:", oper_info.alternate_skill);
            ctrler()->click(skill_vec.at(oper_info.alternate_skill - 1));
            sleep(delay);
        }
        const int skill = m_config->get_theme() == RoguelikeTheme::JieGarden
                              ? jiegarden_prebattle_skill(m_prebattle_stage, name, oper_info.skill)
                              : oper_info.skill;
        if (skill > 0 && static_cast<size_t>(skill) <= skill_vec.size()) {
            LogInfo << "Selecting main skill " << skill << " for " << name;
            ctrler()->click(skill_vec.at(skill - 1));
            sleep(delay);
            m_config->status().selected_skills[name] = skill;
            if (skill != oper_info.skill) {
                auto info = basic_info_with_what("SuiBossSkillSelection");
                info["details"] =
                    json::object { { "stage", m_prebattle_stage }, { "operator", name }, { "skill", skill } };
                callback(AsstMsg::SubTaskExtraInfo, info);
            }
        }
        constexpr int RookieStd = 200;
        if (oper_info.promote_priority < RookieStd) {
            has_rookie = true;
        }
    }

    if (m_config->status().opers.empty()) {
        std::unordered_map<std::string, RoguelikeOper> opers;
        for (const auto& [name, skill_vec] : analyzer.get_result()) {
            opers[name] = { .elite = 1, .level = 80 };
            // 不知道是啥等级随便填一个
        }
        m_config->status().opers = std::move(opers);
    }

    if (analyzer.get_team_full() && !has_rookie) {
        Log.info("Team full and no rookie");
        m_config->status().team_full_without_rookie = true;
    }
    else {
        Log.info("Team not full or has rookie");
        m_config->status().team_full_without_rookie = false;
    }
    return true;
}

void asst::RoguelikeSkillSelectionTaskPlugin::reset_in_run_variables()
{
    m_config->status().selected_skills.clear();
    m_read_preview = false;
    m_prebattle_stage.clear();
}
