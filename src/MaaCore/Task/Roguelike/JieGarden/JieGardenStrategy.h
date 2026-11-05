#pragma once
#include "JieGardenStrategyPolicy.h"
#include "Task/Roguelike/RoguelikeConfig.h"

namespace asst
{
JieGardenTeam jiegarden_team(const RoguelikeConfig& config, bool guests_only = false);
JieGardenTeam jiegarden_guard_team(const RoguelikeConfig& config);
JieGardenRecruitRole jiegarden_recruit_role(const std::string& name);
}
