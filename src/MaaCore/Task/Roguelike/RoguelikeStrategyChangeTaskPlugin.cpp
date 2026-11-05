#include "RoguelikeStrategyChangeTaskPlugin.h"
#include "JieGarden/JieGardenStrategy.h"

#include "Config/TaskData.h"
#include "Utils/Logger.hpp"

bool asst::RoguelikeStrategyChangeTaskPlugin::verify(AsstMsg msg, const json::value& details) const
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
    if (m_config->get_theme() == RoguelikeTheme::JieGarden && task_view == "Roguelike@NextLevel") {
        const auto title = details.get("details", "result", "text", std::string());
        const int floor = jiegarden_observed_floor(title);
        if (floor > 0) {
            m_config->status().floor = floor;
            LogInfo << "Sui floor recognized " << floor << " title " << title;
        }
        return false;
    }
    if (task_view == "Roguelike@StrategyChange") {
        m_result = details.get("details", "result", json::object());
        return true;
    }
    else {
        return false;
    }
}

bool asst::RoguelikeStrategyChangeTaskPlugin::_run()
{
    LogTraceFunction;

    const std::string theme = m_config->get_theme();
    const std::string stages_task_name = theme + "@Roguelike@Stages";
    const std::string current_strategy = m_result.get("text", "");
    if (current_strategy.empty() || current_strategy.find("_SKIP_") != std::string::npos) {
        Log.info("Skip strategy change, current strategy is", current_strategy);
        return true;
    }
    if (theme == RoguelikeTheme::JieGarden && current_strategy == "_progressionF1") {
        m_config->status().floor = 1;
    }
    const std::string strategy_task_name = stages_task_name + current_strategy;

    if (Task.get(strategy_task_name) == nullptr) [[unlikely]] {
        Log.error("Strategy task", strategy_task_name, "doesn't exist!");
        return false;
    }

    const bool restricted = current_strategy.find("boskyPassageDefault") != std::string::npos;
    const auto team = theme == RoguelikeTheme::JieGarden ? jiegarden_team(*m_config, restricted) : JieGardenTeam {};
    const bool cautious = theme == RoguelikeTheme::JieGarden && m_config->jiegarden_strategy().cautious_routing &&
                          jiegarden_needs_growth(team, m_config->status().floor, m_config->get_difficulty());
    const auto selected = cautious ? strategy_task_name + "_localCautious" : strategy_task_name;
    if (Task.get(selected) == nullptr) {
        return false;
    }
    LogInfo << "Sui routing: " << selected << " roster ready " << !cautious << " restricted " << restricted
            << " healers " << team.healers << " blockers " << team.blockers << " carries " << team.damage
            << " E2 carries " << team.elite2_carries << " floor " << m_config->status().floor;
    Task.set_task_base(stages_task_name, selected);

    return true;
}
