#pragma once
#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <vector>

namespace asst
{
// Bind exact reward names to already matched Obtain buttons from the same frame.
// Ambiguity always retains the stock action.
template <typename Names, typename Buttons>
std::optional<size_t>
    select_jiegarden_reward(const std::vector<std::string>& priorities, const Names& names, const Buttons& buttons)
{
    if (buttons.size() < 2 || buttons.size() > 4) {
        return std::nullopt;
    }
    for (size_t i = 0; i < buttons.size(); ++i) {
        const auto& a = buttons[i].rect;
        if (a.width <= 0 || a.height <= 0) {
            return std::nullopt;
        }
        for (size_t j = 0; j < i; ++j) {
            const auto& b = buttons[j].rect;
            if (std::abs(a.y - b.y) > 30 ||
                std::abs((a.x + a.width / 2) - (b.x + b.width / 2)) < (a.width + b.width) / 2) {
                return std::nullopt;
            }
        }
    }
    for (const auto& wanted : priorities) {
        std::optional<size_t> chosen;
        size_t matches = 0;
        for (const auto& name : names) {
            if (name.text != wanted || name.score < 0.9 || name.rect.width <= 0 || name.rect.height <= 0) {
                continue;
            }
            const int center = name.rect.x + name.rect.width / 2;
            for (size_t i = 0; i < buttons.size(); ++i) {
                const auto& button = buttons[i].rect;
                const int gap = button.y - (name.rect.y + name.rect.height);
                if (gap >= 20 && gap <= 360 && std::abs(center - (button.x + button.width / 2)) <= button.width / 3) {
                    chosen = i;
                    ++matches;
                }
            }
        }
        if (matches > 1) {
            return std::nullopt;
        }
        if (chosen) {
            return chosen;
        }
    }
    return std::nullopt;
}
}
