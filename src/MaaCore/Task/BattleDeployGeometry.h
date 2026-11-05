#pragma once

#include <algorithm>
#include <utility>

namespace asst
{
// Keep the facing drag anchored to its tile; shorten it at the screen edge.
inline std::pair<int, int> deployment_facing_endpoint(int x, int y, int dx, int dy, int distance, int width, int height)
{
    return { std::clamp(x + dx * distance, 1, width - 1), std::clamp(y + dy * distance, 1, height - 1) };
}
}
