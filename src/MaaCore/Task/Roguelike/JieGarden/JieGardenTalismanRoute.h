#pragma once

#include <algorithm>
#include <array>
#include <utility>

namespace asst
{
struct JieGardenRouteEvidence
{
    int upper = 0;
    int lower = 0;
};

// Inspect interior tiles only: spawn gates, the goal, and the central thorn lane are excluded.
// A route segment must occupy most scan columns; isolated red eyes or damage numbers do not qualify.
template <typename Pixel>
JieGardenRouteEvidence sample_jiegarden_talisman_route(
    int width,
    int height,
    Pixel pixel,
    const std::array<std::pair<int, int>, 7>& upper,
    const std::array<std::pair<int, int>, 7>& lower)
{
    auto scan = [&](const auto& centers) {
        int segments = 0;
        int first = -1;
        int last = -1;
        const int radius_x = std::max(6, width * 16 / 1280);
        const int radius_y = std::max(4, height * 12 / 720);
        for (int index = 0; index < 7; ++index) {
            const auto [cx, cy] = centers[index];
            if (cx - radius_x < 0 || cx + radius_x >= width || cy - radius_y < 0 || cy + radius_y >= height) {
                continue;
            }
            int columns = 0;
            for (int x = cx - radius_x; x <= cx + radius_x; ++x) {
                bool red = false;
                for (int y = cy - radius_y; y <= cy + radius_y; ++y) {
                    const auto color = pixel(x, y);
                    const int r = color[0], g = color[1], b = color[2];
                    red |= r >= 150 && r > g * 3 / 2 && r > b * 3 / 2;
                }
                columns += red;
            }
            if (columns >= radius_x * 3 / 2) {
                ++segments;
                if (first < 0) {
                    first = index;
                }
                last = index;
            }
        }
        return last - first >= 3 ? segments : 0;
    };
    return { scan(upper), scan(lower) };
}

class JieGardenRouteVote
{
public:
    void observe(const JieGardenRouteEvidence& evidence)
    {
        upper_votes += evidence.upper >= 3;
        lower_votes += evidence.lower >= 3;
    }

    // Require two separate observations of one route and no contradictory route evidence.
    int dangerous_row() const
    {
        if (upper_votes >= 2 && lower_votes == 0) {
            return 2;
        }
        if (lower_votes >= 2 && upper_votes == 0) {
            return 4;
        }
        return 0;
    }

    int upper_votes = 0;
    int lower_votes = 0;
};
}
