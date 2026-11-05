#include "RoguelikeRewardSelectionTaskPlugin.h"
#include "Config/TaskData.h"
#include "JieGardenRewardSelection.h"
#include "Utils/DebugImageHelper.hpp"
#include "Utils/Logger.hpp"
#include "Vision/MultiMatcher.h"
#include "Vision/OCRer.h"

bool asst::RoguelikeRewardSelectionTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    return m_config->get_theme() == RoguelikeTheme::JieGarden && msg == AsstMsg::SubTaskStart &&
           details.get("subtask", std::string()) == "ProcessTask" &&
           details.get("details", "task", std::string()) == "JieGarden@Roguelike@GetDropSelectReward";
}

bool asst::RoguelikeRewardSelectionTaskPlugin::_run()
{
    auto* process = dynamic_cast<ProcessTask*>(m_task_ptr);
    const auto image = get_hit_image();
    if (!process || !image || image->empty()) {
        return true;
    }
    const auto hit = process->get_last_hit();
    if (!hit || hit->task_ptr->action != ProcessTaskAction::ClickSelf || !hit->task_ptr->rect_move.empty()) {
        return true;
    }
    MultiMatcher buttons(*image);
    buttons.set_task_info("JieGarden@Roguelike@GetDropSelectReward");
    OCRer names(*image);
    names.set_task_info("JieGarden@Roguelike@PreferredRewardNames");
    const bool have_buttons = buttons.analyze().has_value();
    const bool have_names = names.analyze().has_value();
    const auto task = Task.get<OcrTaskInfo>("JieGarden@Roguelike@PreferredRewardNames");
    const auto selected = have_buttons && have_names && task
                              ? select_jiegarden_reward(task->text, names.get_result(), buttons.get_result())
                              : std::nullopt;
    if (m_saved < 8) {
        utils::save_debug_image(
            *image,
            utils::path("debug") / "roguelike" / "rewards",
            true,
            "Sui relic reward evidence",
            selected ? "preferred" : "stock");
        ++m_saved;
    }
    auto info = basic_info_with_what("SuiRelicRewardSelection");
    info["details"] = json::object {
        { "decision", selected ? "preferred_verified_button" : "stock_fallback" },
        { "button_count", have_buttons ? buttons.get_result().size() : 0 },
        { "preferred_names", json::array() },
    };
    if (have_names) {
        for (const auto& name : names.get_result()) {
            info["details"]["preferred_names"].as_array().emplace_back(name.text);
        }
    }
    if (selected) {
        // ProcessTask runs its normal ClickSelf after this callback using this shared hit.
        // Do not send a separate click or change recruitment/Tongbao reward tasks.
        hit->rect = buttons.get_result()[*selected].rect;
        info["details"]["button_index"] = *selected;
        LogInfo << "Sui preferred relic reward button " << *selected;
    }
    callback(AsstMsg::SubTaskExtraInfo, info);
    return true;
}
