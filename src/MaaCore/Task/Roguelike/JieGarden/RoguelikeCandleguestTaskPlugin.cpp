#include "RoguelikeCandleguestTaskPlugin.h"
#include "Config/Roguelike/RoguelikeRecruitConfig.h"
#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "JieGardenStrategy.h"
#include "Utils/Logger.hpp"
#include "Vision/OCRer.h"
#include <algorithm>

bool asst::RoguelikeCandleguestTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }
    const auto task = details.get("details", "task", std::string());
    m_confirming = task == "JieGarden@Roguelike@LocalCandleguestConfirm";
    return (m_confirming && msg == AsstMsg::SubTaskCompleted) ||
           (task == "JieGarden@Roguelike@LocalCandleguestSelect" && msg == AsstMsg::SubTaskStart);
}

bool asst::RoguelikeCandleguestTaskPlugin::_run()
{
    auto stop = [&]() {
        m_pending.clear();
        m_task_ptr->set_enable(false);
        return false;
    };
    if (!m_config->jiegarden_strategy().auto_candleguest) {
        LogInfo << "Automatic Candleguest conversion disabled; stopping for manual selection";
        return stop();
    }
    if (m_confirming) {
        OCRer check(ctrler()->get_image());
        check.set_task_info("JieGarden@Roguelike@LocalCandleguestFlag");
        if (check.analyze()) {
            LogWarn << "Candleguest confirmation did not leave selection screen; preserving run";
            return stop();
        }
        if (!m_pending.empty()) {
            m_config->status().candleguests.insert(m_pending);
            LogInfo << "Candleguest confirmed: " << m_pending;
            m_pending.clear();
        }
        return true;
    }
    m_pending.clear();
    const std::string theme(RoguelikeTheme::JieGarden);
    std::unordered_set<std::string> candidates;
    for (const auto& group : { "主力输出", "稳定治疗", "奶盾", "重装", "回费", "地面远程", "多段处理" }) {
        for (const auto& name : RoguelikeRecruit.get_group_info(theme, group).opers) {
            if (!m_config->status().candleguests.contains(name)) {
                candidates.insert(name);
            }
        }
    }
    OCRer names(ctrler()->get_image());
    names.set_task_info("JieGarden@Roguelike@LocalCandleguestNames");
    const auto replace = Task.get<OcrTaskInfo>("CharsNameOcrReplace");
    names.set_replace(replace->replace_map, replace->replace_full);
    names.set_required(std::vector<std::string>(candidates.begin(), candidates.end()));
    const auto result = names.analyze();
    if (!result || result->empty()) {
        LogWarn << "No eligible Candleguest name recognized; preserving selection screen";
        return stop();
    }
    const auto guests = jiegarden_team(*m_config, true);
    auto score = [&](const std::string& name) {
        const auto role = jiegarden_recruit_role(name);
        int value = RoguelikeRecruit.get_oper_info(theme, name).recruit_priority;
        value += jiegarden_candleguest_bonus(role, name == "电弧", guests);
        if (const auto it = m_config->status().opers.find(name); it != m_config->status().opers.end()) {
            value += it->second.elite == 2 ? 1000 : 0;
            if (name == "电弧" && it->second.elite == 2 && m_config->get_difficulty() >= 9) {
                value += 15'000;
            }
        }
        return value;
    };
    const auto selected =
        std::ranges::max_element(*result, [&](const auto& a, const auto& b) { return score(a.text) < score(b.text); });
    m_pending = selected->text;
    LogInfo << "Selecting Candleguest: " << m_pending << " priority " << score(m_pending);
    if (!ctrler()->click(selected->rect)) {
        return stop();
    }
    return true;
}
