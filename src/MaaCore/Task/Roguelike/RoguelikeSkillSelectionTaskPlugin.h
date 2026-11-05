#pragma once

#include <unordered_map>

#include "AbstractRoguelikeTaskPlugin.h"

namespace asst
{
class RoguelikeSkillSelectionTaskPlugin final : public AbstractRoguelikeTaskPlugin
{
public:
    using AbstractRoguelikeTaskPlugin::AbstractRoguelikeTaskPlugin;
    virtual ~RoguelikeSkillSelectionTaskPlugin() override = default;

    virtual bool verify(AsstMsg msg, const json::value& details) const override;
    virtual void reset_in_run_variables() override;

protected:
    virtual bool _run() override;

private:
    mutable bool m_read_preview = false;
    std::string m_prebattle_stage;
};
}
