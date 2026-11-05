#pragma once
#include <cstddef>
#include <optional>
#include <string_view>

namespace asst
{
inline int jiegarden_opening_preference(std::string_view name)
{
    return name == "电弧" ? 2 : name == "维什戴尔" ? 1 : 0;
}

inline bool jiegarden_secondary_opener(std::string_view name)
{
    return name == "卡达" || name == "蕾缪安";
}

// Affordability does not change the opening choice: reserve DP for the chosen carry.
template <typename Operators, typename Eligible, typename Priority>
std::optional<size_t> jiegarden_opening_carry(const Operators& operators, Eligible eligible, Priority priority)
{
    std::optional<size_t> best;
    for (size_t index = 0; index < operators.size(); ++index) {
        const auto& oper = operators[index];
        if (oper.cooling || !eligible(oper)) {
            continue;
        }
        if (!best || priority(oper) > priority(operators[*best])) {
            best = index;
        }
    }
    return best;
}
}
