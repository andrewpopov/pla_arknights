#pragma once

#include <cctype>
#include <string>
#include <string_view>

namespace asst
{
// Match whole OCR headers; do not infer a trade from a partial effect or its position.
inline std::string jiegarden_bosky_option_key(std::string_view text)
{
    std::string key;
    for (unsigned char ch : text) {
        if (ch >= 128 || std::isalnum(ch)) {
            key.push_back(ch < 128 ? static_cast<char>(std::tolower(ch)) : static_cast<char>(ch));
        }
    }
    return key;
}

inline int jiegarden_tavern_option_priority(std::string_view text, bool allow_trade, int current_hp = -1)
{
    const auto key = jiegarden_bosky_option_key(text);
    if (allow_trade && key == "replicatesuisform") {
        return 100;
    }
    // Yu trades ten ingots for six life. Only use a recognized low-life reading;
    // an enabled option is still required by the encounter selector.
    if (allow_trade && current_hp >= 1 && current_hp <= 6 && (key == "找余果腹" || key == "askyuforameal")) {
        return 300;
    }
    // Dusk exchanges ten ingots for five shields. Never substitute an LP-cost trade.
    if (allow_trade && (key == "askdusktotouchupyourbody" || key == "makeanotherdrawing")) {
        return 200;
    }
    if (key == "还是算了" || key == "离开" || key == "forgetit" || key == "leave" || key == "leavefornow" ||
        key == "thatsenough" || key == "enoughfornow") {
        return 10;
    }
    return 0;
}

inline bool jiegarden_bosky_revisit_allowed(unsigned visits)
{
    // Unvisited nodes always take precedence. Bound repeated visits even if candles are misread.
    return visits > 0 && visits < 3;
}
}
