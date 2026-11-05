#pragma once
#include "JieGardenStrategyPolicy.h"
#include <algorithm>
#include <cstdlib>
#include <string_view>

namespace asst
{
inline bool avoid_jiegarden_long_march(const JieGardenTeam& team, int difficulty, bool enabled)
{
    return enabled && difficulty >= 9 && team.healers == 0 && team.elite2_carries == 0;
}

// Avoid demonstrated high-risk stages and unsupported healerless midfloor fights.
inline bool avoid_jiegarden_stage(std::string_view stage, const JieGardenTeam& team, int difficulty, bool enabled)
{
    return enabled && (stage == "砺锋" || (stage == "御外侮" && difficulty >= 9) ||
                       ((stage == "忍气不吞声" || stage == "暗箭难防" || stage == "啖之以利") && difficulty >= 9 &&
                        team.healers == 0) ||
                       (stage == "长驱不复" && avoid_jiegarden_long_march(team, difficulty, enabled)));
}

// Preview only siblings; adjacent columns may belong to a different route step.
template <typename Rect>
inline bool jiegarden_sibling_candidate(const Rect& original, const Rect& candidate)
{
    const int dx = std::abs((original.x + original.width / 2) - (candidate.x + candidate.width / 2));
    const int dy = std::abs((original.y + original.height / 2) - (candidate.y + candidate.height / 2));
    return dx <= std::max(original.width, candidate.width) / 2 && dy > std::max(original.height, candidate.height) / 2;
}
}
