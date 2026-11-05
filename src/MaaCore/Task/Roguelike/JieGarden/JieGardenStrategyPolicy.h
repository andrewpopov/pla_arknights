#pragma once
#include <string_view>

namespace asst
{
struct JieGardenStrategyOptions
{
    bool conserve_vouchers = true;
    bool manage_coppers = true;
    bool auto_candleguest = true;
    bool cautious_routing = true;
};

struct JieGardenTeam
{
    int healers = 0;
    int blockers = 0;
    int damage = 0;
    int vanguards = 0;
    int total = 0;
    int utility = 0;
    int elite2_carries = 0;

    bool ready() const { return healers > 0 && blockers > 0 && damage > 0 && total >= 4; }
};

enum class JieGardenRecruitRole
{
    Other,
    Healer,
    Blocker,
    Damage,
    Vanguard,
    Core,
    Utility
};

inline bool conserve_jiegarden_candidate(
    const JieGardenTeam& team,
    JieGardenRecruitRole role,
    bool initial,
    bool promotion,
    bool temporary)
{
    if (initial || promotion || temporary) {
        return false;
    }
    switch (role) {
    case JieGardenRecruitRole::Core:
        return team.ready() && team.damage >= 2;
    case JieGardenRecruitRole::Utility:
        return team.utility >= 2;
    case JieGardenRecruitRole::Healer:
        return team.healers >= 2;
    case JieGardenRecruitRole::Blocker:
        return team.blockers >= 2;
    case JieGardenRecruitRole::Vanguard:
        return team.vanguards >= 1;
    case JieGardenRecruitRole::Damage:
        return team.ready() && team.damage >= 2;
    case JieGardenRecruitRole::Other:
        return team.ready() && team.total >= 6;
    default:
        return false;
    }
}

// Save Hope for the first E2 carry without withholding a missing survival role.
inline bool jiegarden_save_for_first_promotion(
    const JieGardenTeam& team,
    JieGardenRecruitRole role,
    int difficulty,
    bool initial,
    bool promotion,
    bool temporary)
{
    if (difficulty < 9 || initial || promotion || temporary || team.elite2_carries > 0) {
        return false;
    }
    switch (role) {
    case JieGardenRecruitRole::Core:
    case JieGardenRecruitRole::Damage:
        return team.damage > 0;
    case JieGardenRecruitRole::Healer:
        return team.healers > 0;
    case JieGardenRecruitRole::Blocker:
        return team.blockers > 0;
    case JieGardenRecruitRole::Vanguard:
        return team.vanguards > 0;
    case JieGardenRecruitRole::Utility:
        return team.utility > 0;
    default:
        return team.total >= 3;
    }
}

inline bool conserve_jiegarden_guard(const JieGardenTeam& team, bool initial, bool promotion, bool temporary)
{
    return !initial && !promotion && !temporary && team.damage > 0 && team.blockers > 0;
}

inline int jiegarden_promotion_bonus(std::string_view name, bool promotion, int candidate_elite, int difficulty)
{
    if (difficulty < 9 || !promotion || candidate_elite != 2) {
        return 0;
    }
    return name == "电弧" ? 8000 : name == "维什戴尔" ? 4000 : 0;
}

inline int jiegarden_observed_floor(std::string_view title)
{
    if (title == "洪陆楼" || title == "Honglu Tower") {
        return 1;
    }
    if (title == "山水阁" || title == "Shanshui Pavilion") {
        return 2;
    }
    if (title == "云瓦亭" || title == "Yunwa Gazebo") {
        return 3;
    }
    if (title == "汝吾门" || title == "Ruwu Gate") {
        return 4;
    }
    if (title == "见字祠" || title == "Jianzi Shrine") {
        return 5;
    }
    if (title == "始末陵" || title == "Shimo Tomb") {
        return 6;
    }
    return 0;
}

inline bool jiegarden_needs_growth(const JieGardenTeam& team, int floor, int difficulty)
{
    return !team.ready() || (difficulty >= 10 && floor >= 2 && team.elite2_carries == 0);
}

inline int jiegarden_candleguest_bonus(JieGardenRecruitRole role, bool is_raidian, const JieGardenTeam& guests)
{
    // Build a functioning restricted squad before converting a second carry.
    if (guests.damage == 0 && role == JieGardenRecruitRole::Core) {
        return is_raidian ? 12'000 : 11'000;
    }
    if (guests.damage > 0 && guests.healers == 0 && role == JieGardenRecruitRole::Healer) {
        return 12'000;
    }
    if (guests.damage > 0 && guests.healers > 0 && guests.blockers == 0 && role == JieGardenRecruitRole::Blocker) {
        return 11'000;
    }
    if (is_raidian) {
        return 9000;
    }
    if (role == JieGardenRecruitRole::Core) {
        return 8000;
    }
    if (role == JieGardenRecruitRole::Healer) {
        return 6000;
    }
    if (role == JieGardenRecruitRole::Blocker) {
        return 4000;
    }
    return 0;
}

inline bool retry_jiegarden_deploy(int failed_attempts)
{
    return failed_attempts < 2;
}

inline bool unsafe_jiegarden_copper(std::string_view name, const JieGardenTeam& team)
{
    // These effects invalidate authored facing, target assignment, or opening timing.
    if (name == "厉-人间长存" || name == "厉-生材百相" || name == "厉-孤芳自赏" || name == "厉-天命难违" ||
        name == "厉-寒窗志" || name == "厉-见灵光") {
        return true;
    }
    if (name == "厉-战血流" || name == "厉-药食" || name == "厉-遇良弈") {
        return team.healers == 0 || team.blockers == 0;
    }
    if (name == "厉-待机缘") {
        return team.vanguards == 0;
    }
    return false;
}
}
