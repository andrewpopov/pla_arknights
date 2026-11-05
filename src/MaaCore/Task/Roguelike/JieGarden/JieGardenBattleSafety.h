#pragma once
#include <chrono>
#include <string_view>

namespace asst
{
inline int jiegarden_prebattle_skill(std::string_view stage, std::string_view name, int configured_skill)
{
    return stage == "破岁阵祀" && name == "电弧" ? 1 : configured_skill;
}

inline bool use_jiegarden_dark_arrows_s2_plan(std::string_view stage, int raidian_elite, int selected_skill)
{
    return stage == "暗箭难防" && raidian_elite == 2 && selected_skill == 2;
}

inline bool use_jiegarden_boss_s1_plan(std::string_view stage, int raidian_elite, int selected_skill)
{
    return stage == "破岁阵祀" && raidian_elite == 2 && selected_skill == 1;
}

inline bool stop_stalled_jiegarden_battle(std::chrono::steady_clock::duration elapsed)
{
    return elapsed >= std::chrono::minutes(8);
}

// A future command for the same tile keeps it usable until its own window closes.
template <typename Location, typename Plans>
bool expired_jiegarden_deploy_location(int kills, const Location& location, const Plans& plans)
{
    bool found = false;
    for (const auto& [group, commands] : plans) {
        for (const auto& command : commands) {
            if (command.location == location) {
                found = true;
                if (kills <= command.kill_upper_bound) {
                    return false;
                }
            }
        }
    }
    return found;
}
}
