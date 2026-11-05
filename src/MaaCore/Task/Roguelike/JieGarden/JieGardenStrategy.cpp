#include "JieGardenStrategy.h"
#include "Config/Miscellaneous/BattleDataConfig.h"
#include "Config/Roguelike/RoguelikeRecruitConfig.h"

asst::JieGardenTeam asst::jiegarden_team(const RoguelikeConfig& config, bool guests_only)
{
    auto count = [&](std::initializer_list<const char*> names) {
        std::unordered_set<std::string> members;
        for (auto name : names) {
            const auto& group = RoguelikeRecruit.get_group_info(std::string(RoguelikeTheme::JieGarden), name);
            for (const auto& oper : group.opers) {
                if (guests_only ? config.status().candleguests.contains(oper) : config.status().opers.contains(oper)) {
                    members.insert(oper);
                }
            }
        }
        return static_cast<int>(members.size());
    };
    JieGardenTeam team { count({ "稳定治疗" }),
                         count({ "奶盾", "重装", "挡人先锋" }),
                         count({ "主力输出" }),
                         count({ "回费" }),
                         static_cast<int>(
                             guests_only ? config.status().candleguests.size() : config.status().opers.size()),
                         count({ "多段处理" }) };
    for (const auto& [name, info] : config.status().opers) {
        if (info.elite == 2 && (!guests_only || config.status().candleguests.contains(name)) &&
            jiegarden_recruit_role(name) == JieGardenRecruitRole::Core) {
            ++team.elite2_carries;
        }
    }
    return team;
}

asst::JieGardenTeam asst::jiegarden_guard_team(const RoguelikeConfig& config)
{
    auto team = jiegarden_team(config);
    const std::string theme(RoguelikeTheme::JieGarden);
    // Persistent blocking Guards can already hold the lane even without a Defender.
    const auto& blockers = RoguelikeRecruit.get_group_info(theme, "地面阻挡").opers;
    for (const auto& name : blockers) {
        if (config.status().opers.contains(name) && BattleData.get_roles(name, true).contains(battle::Role::Warrior) &&
            RoguelikeRecruit.get_oper_info(theme, name).auto_retreat == 0) {
            team.blockers = std::max(team.blockers, 1);
            break;
        }
    }
    return team;
}

asst::JieGardenRecruitRole asst::jiegarden_recruit_role(const std::string& name)
{
    const auto& theme = std::string(RoguelikeTheme::JieGarden);
    auto member = [&](const char* group) {
        return RoguelikeRecruit.get_group_info(theme, group).opers.contains(name);
    };
    if (member("主力输出")) {
        return JieGardenRecruitRole::Core;
    }
    if (member("多段处理")) {
        return JieGardenRecruitRole::Utility;
    }
    if (member("稳定治疗")) {
        return JieGardenRecruitRole::Healer;
    }
    if (member("回费")) {
        return JieGardenRecruitRole::Vanguard;
    }
    if (member("奶盾") || member("重装")) {
        return JieGardenRecruitRole::Blocker;
    }
    if (member("高台输出") || member("近卫")) {
        return JieGardenRecruitRole::Damage;
    }
    return JieGardenRecruitRole::Other;
}
