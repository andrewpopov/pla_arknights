#pragma once
#include "Task/Roguelike/AbstractRoguelikeTaskPlugin.h"

namespace asst
{
class RoguelikeRewardSelectionTaskPlugin : public AbstractRoguelikeTaskPlugin
{
public:
    using AbstractRoguelikeTaskPlugin::AbstractRoguelikeTaskPlugin;
    bool verify(AsstMsg msg, const json::value& details) const override;

    void reset_in_run_variables() override { m_saved = 0; }

protected:
    bool _run() override;

private:
    int m_saved = 0;
};
}
