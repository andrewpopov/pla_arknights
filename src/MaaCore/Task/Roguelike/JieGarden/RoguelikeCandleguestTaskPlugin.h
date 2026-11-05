#pragma once
#include "Task/Roguelike/AbstractRoguelikeTaskPlugin.h"

namespace asst
{
class RoguelikeCandleguestTaskPlugin : public AbstractRoguelikeTaskPlugin
{
public:
    using AbstractRoguelikeTaskPlugin::AbstractRoguelikeTaskPlugin;
    bool verify(AsstMsg msg, const json::value& details) const override;

    void reset_in_run_variables() override { m_pending.clear(); }

protected:
    bool _run() override;

private:
    mutable bool m_confirming = false;
    std::string m_pending;
};
}
