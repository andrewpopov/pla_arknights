#pragma once
#include "Task/Roguelike/AbstractRoguelikeTaskPlugin.h"

namespace asst
{
class RoguelikeStageReadinessTaskPlugin : public AbstractRoguelikeTaskPlugin
{
public:
    using AbstractRoguelikeTaskPlugin::AbstractRoguelikeTaskPlugin;
    bool verify(AsstMsg msg, const json::value& details) const override;
    void reset_in_run_variables() override;

protected:
    bool _run() override;

private:
    std::string preview_stage_name(const cv::Mat& image) const;
    bool normal_entry_available(const cv::Mat& image) const;
    void report(const std::string& decision, const std::string& selected, const JieGardenTeam& team);
    mutable bool m_restricted = false;
    mutable bool m_entry_check = false;
    bool m_allow_forced_entry = false;
    mutable std::string m_source_task;
    std::string m_avoided_stage;
};
}
