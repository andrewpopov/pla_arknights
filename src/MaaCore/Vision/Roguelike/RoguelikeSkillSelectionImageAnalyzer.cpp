#include "RoguelikeSkillSelectionImageAnalyzer.h"

#include "MaaUtils/NoWarningCV.hpp"

#include "Config/Miscellaneous/BattleDataConfig.h"
#include "Config/Roguelike/RoguelikeRecruitConfig.h"
#include "Config/TaskData.h"
#include "Utils/Logger.hpp"
#include "Utils/StringMisc.hpp"
#include "Vision/Matcher.h"
#include "Vision/MultiMatcher.h"
#include "Vision/OCRer.h"
#include "Vision/RegionOCRer.h"

bool asst::RoguelikeSkillSelectionImageAnalyzer::analyze()
{
    m_result.clear();
    m_team_full = false;
    MultiMatcher flag_analyzer(m_image);
    flag_analyzer.set_task_info("RoguelikeSkillSelectionFlag");

    const bool has_flags = flag_analyzer.analyze().has_value();
    if (!has_flags) {
        Matcher formation(m_image);
        formation.set_task_info("Roguelike@StartAction");
        if (!formation.analyze()) {
            return false;
        }
    }

    const auto& flags = flag_analyzer.get_result();

    if (flags.size() > 13) {
        // https://github.com/MaaAssistantArknights/MaaAssistantArknights/issues/669
        // 不知道为什么会匹配出来一堆结果，得分完全相同，坐标间隔还特别有规律。这种情况直接报错然后重试
        Log.error("Too many flags");
        return false;
    }

    int unknown_index = 0;
    for (const auto& flag : flags) {
        std::string name = name_analyze(flag.rect);
        auto skills = skill_analyze(flag.rect);
        if (skills.empty()) {
            continue;
        }
        if (name.empty()) {
            name = "Unknown" + std::to_string(unknown_index++);
        }
        m_result.emplace(std::move(name), std::move(skills));
    }

    recognize_unmarked_names();
    if (m_result.size() > 13) {
        LogWarn << __FUNCTION__ << "too many recognized formation rows" << m_result.size();
        m_result.clear();
        return false;
    }
    team_full_analyze();

    return !m_result.empty();
}

void asst::RoguelikeSkillSelectionImageAnalyzer::recognize_unmarked_names()
{
    // Candleguest cards replace the normal row marker but keep the name and skill layout.
    const auto name_task = Task.get<OcrTaskInfo>("RoguelikeSkillSelectionName");
    const auto replace_task = Task.get<OcrTaskInfo>("CharsNameOcrReplace");
    for (const auto& column : { "RoguelikeSkillSelectionNamesLeft", "RoguelikeSkillSelectionNamesRight" }) {
        const auto column_task = Task.get<OcrTaskInfo>(column);
        OCRer names(m_image);
        names.set_task_info(column_task);
        names.set_replace(replace_task->replace_map, replace_task->replace_full);
        const auto results = names.analyze();
        if (!results) {
            continue;
        }
        for (const auto& result : *results) {
            if (m_result.contains(result.text) || !BattleData.get_first_id(battle::Role::Unknown, result.text, true)) {
                continue;
            }
            const Rect anchor { column_task->roi.x - name_task->roi.x, result.rect.y - name_task->roi.y, 63, 34 };
            if (anchor.y < 0 || name_analyze(anchor) != result.text) {
                continue;
            }
            auto skills = skill_analyze(anchor);
            if (std::ranges::any_of(skills, [&](const auto& rect) {
                    return rect.x < 0 || rect.y < 0 || rect.x + rect.width > m_image.cols ||
                           rect.y + rect.height > m_image.rows;
                })) {
                continue;
            }
            LogInfo << __FUNCTION__ << "recovered unmarked skill row" << result.text;
            m_result.emplace(result.text, std::move(skills));
        }
    }
}

std::string asst::RoguelikeSkillSelectionImageAnalyzer::name_analyze(const Rect& roi)
{
    RegionOCRer analyzer(m_image);
    auto name_task_ptr = Task.get<OcrTaskInfo>("RoguelikeSkillSelectionName");
    analyzer.set_task_info(name_task_ptr);
    analyzer.set_roi(roi.move(name_task_ptr->roi));
    analyzer.set_replace(
        std::dynamic_pointer_cast<OcrTaskInfo>(Task.get("CharsNameOcrReplace"))->replace_map,
        std::dynamic_pointer_cast<OcrTaskInfo>(Task.get("CharsNameOcrReplace"))->replace_full);

    if (!analyzer.analyze()) {
        return {};
    }
    return analyzer.get_result().text;
}

std::vector<asst::Rect> asst::RoguelikeSkillSelectionImageAnalyzer::skill_analyze(const Rect& roi)
{
    static const std::array<std::string, 3> TasksName = {
        "RoguelikeSkillSelectionMove1",
        "RoguelikeSkillSelectionMove2",
        "RoguelikeSkillSelectionMove3",
    };
    std::vector<Rect> result;
    result.reserve(TasksName.size());

    for (const std::string& task_name : TasksName) {
        result.emplace_back(roi.move(Task.get(task_name)->rect_move));
    }
    return result;
}

void asst::RoguelikeSkillSelectionImageAnalyzer::team_full_analyze()
{
    Matcher analyzer(m_image);
    analyzer.set_task_info("RoguelikeSkillSelectionTeamFull");
    m_team_full = !analyzer.analyze();
}
