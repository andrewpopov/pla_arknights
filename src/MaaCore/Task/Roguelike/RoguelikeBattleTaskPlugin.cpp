#include "RoguelikeBattleTaskPlugin.h"

#include <chrono>
#include <future>
#include <ranges>
#include <vector>

#include "Config/GeneralConfig.h"
#include "Config/Miscellaneous/BattleDataConfig.h"
#include "Config/Miscellaneous/TilePack.h"
#include "Config/Roguelike/RoguelikeCopilotConfig.h"
#include "Config/Roguelike/RoguelikeRecruitConfig.h"
#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "JieGarden/JieGardenBattleSafety.h"
#include "JieGarden/JieGardenOpening.h"
#include "JieGarden/JieGardenStrategy.h"
#include "JieGarden/JieGardenStrategyPolicy.h"
#include "JieGarden/JieGardenTalismanRoute.h"
#include "Task/ProcessTask.h"
#include "Utils/DebugImageHelper.hpp"
#include "Utils/Logger.hpp"
#include "Vision/Matcher.h"
#include "Vision/RegionOCRer.h"

using namespace asst::battle;
using namespace asst::battle::roguelike;

asst::RoguelikeBattleTaskPlugin::RoguelikeBattleTaskPlugin(
    const AsstCallback& callback,
    Assistant* inst,
    std::string_view task_chain,
    const std::shared_ptr<RoguelikeConfig>& roguelike_config_ptr,
    const std::shared_ptr<RoguelikeControlTaskPlugin>& control) :
    AbstractRoguelikeTaskPlugin(callback, inst, task_chain, roguelike_config_ptr, control),
    BattleHelper(inst)
{
}

bool asst::RoguelikeBattleTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (msg != AsstMsg::SubTaskCompleted || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }

    if (!RoguelikeConfig::is_valid_theme(m_config->get_theme())) {
        Log.error("Roguelike name doesn't exist!");
        return false;
    }
    const std::string roguelike_name = m_config->get_theme() + "@";
    const std::string& task = details.get("details", "task", "");
    std::string_view task_view = task;
    if (task_view.starts_with(roguelike_name)) {
        task_view.remove_prefix(roguelike_name.length());
    }
    if (task_view == "Roguelike@StartAction") {
        return true;
    }
    else {
        return false;
    }
}

bool asst::RoguelikeBattleTaskPlugin::_run()
{
    using namespace std::chrono_literals;
    LogTraceFunction;

    if (!calc_stage_info()) {
        return false;
    }

    const int talisman_row = recognize_jiegarden_talisman_route();
    if (need_exit()) {
        return true;
    }
    if (!update_deployment(true)) {
        Log.error("update deployment failed");
        return false;
    }

    cache_oper_elite_status();
    if (!apply_jiegarden_talisman_route(talisman_row)) {
        return true;
    }
    speed_up();
    bool timeout = false;
    auto start_time = std::chrono::steady_clock::now();
    cv::Mat image, image_prev;
    while (!need_exit()) {
        // 不在战斗场景，且已使用过了干员，说明已经打完了，就结束循环
        image = ctrler()->get_image();
        if (!do_once(image, image_prev) && !m_first_deploy) {
            break;
        }
        image_prev = std::move(image);

        auto duration = std::chrono::steady_clock::now() - start_time;
        if (m_config->get_theme() == RoguelikeTheme::JieGarden && stop_stalled_jiegarden_battle(duration)) {
            Matcher running(image_prev);
            running.set_task_info("BattlePauseCancelCheck");
            if (running.analyze()) {
                pause();
            }
            save_map(ctrler()->get_image());
            LogWarn << "Sui battle stalled; stopping without retreating or abandoning: " << m_stage_name;
            m_task_ptr->set_enable(false);
            return true;
        }
        if (!timeout && duration > 8min) {
            timeout = true;
            Log.info("Timeout, retreat!");
            // 超时了，一般是某个怪被干员卡住了，一直不结束。
            all_melee_retreat();
        }
        else if (timeout && duration > 10min) {
            Log.info("Timeout again, abandon!");
            // 超时撤退了还一直卡着，只能放弃了
            abandon();
            break;
        }
    }
    // 通知战斗结束，无论成功与否
    auto info = basic_info_with_what("RoguelikeCombatEnd");
    if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
        auto& details = info["details"];
        details["stage"] = m_stage_name;
        details["kills"] = m_kills;
        details["total_kills"] = m_total_kills;
        details["last_tracked_operators"] = json::array();
        for (const auto& [oper_tag, location] : m_battlefield_opers) {
            details["last_tracked_operators"].as_array().emplace_back(
                json::object { { "name", oper_tag.name }, { "tile", json::array { location.x, location.y } } });
        }
        details["failed_placements"] = json::array();
        for (const auto& [location, attempts] : m_deploy_failure_counts) {
            details["failed_placements"].as_array().emplace_back(
                json::object { { "tile", json::array { location.x, location.y } }, { "attempts", attempts } });
        }
        // Battle end alone does not establish victory or defeat. Preserve its final HUD for review.
        utils::save_debug_image(
            image_prev,
            utils::path("debug") / "roguelike" / "battle-end",
            true,
            "Sui battle-end evidence",
            m_stage_name,
            "jpeg",
            { cv::IMWRITE_JPEG_QUALITY, 90 });
    }
    callback(AsstMsg::SubTaskExtraInfo, info);
    return true;
}

int asst::RoguelikeBattleTaskPlugin::recognize_jiegarden_talisman_route()
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || m_stage_name != "长驱不复") {
        return 0;
    }
    std::array<std::pair<int, int>, 7> upper, lower;
    for (int x = 2; x <= 8; ++x) {
        if (!m_normal_tile_info.contains({ x, 2 }) || !m_normal_tile_info.contains({ x, 4 })) {
            return 0;
        }
        const auto a = m_normal_tile_info.at({ x, 2 }).pos;
        const auto b = m_normal_tile_info.at({ x, 4 }).pos;
        upper[x - 2] = { a.x, a.y };
        lower[x - 2] = { b.x, b.y };
    }
    JieGardenRouteVote vote;
    const auto start = std::chrono::steady_clock::now();
    std::optional<std::chrono::steady_clock::time_point> visible;
    int saved = 0;
    cv::Mat last;
    // Observe before deployment/skill animations obscure the opening path. Do not speed up here.
    while (!need_exit() && std::chrono::steady_clock::now() - start < std::chrono::seconds(8)) {
        last = ctrler()->get_image();
        if (last.empty() || last.type() != CV_8UC3) {
            if (!sleep(100)) {
                break;
            }
            continue;
        }
        const bool hud = check_pause_button(last);
        if (hud && !visible) {
            visible = std::chrono::steady_clock::now();
        }
        // The title fade can hide the HUD while the path is already visible.
        const auto evidence = sample_jiegarden_talisman_route(
            last.cols,
            last.rows,
            [&](int x, int y) {
                const auto bgr = last.at<cv::Vec3b>(y, x);
                return std::array<int, 3> { bgr[2], bgr[1], bgr[0] };
            },
            upper,
            lower);
        vote.observe(evidence);
        if (saved < 4 &&
            (evidence.upper >= 3 || evidence.lower >= 3 ||
             (visible && std::chrono::steady_clock::now() - *visible >= std::chrono::milliseconds(saved * 400)))) {
            utils::save_debug_image(
                last,
                utils::path("debug") / "roguelike" / "talisman-route",
                true,
                "Sui opening route evidence",
                "route");
            ++saved;
        }
        // Keep observing for contradictions instead of locking in on the first flash.
        if (visible && std::chrono::steady_clock::now() - *visible >= std::chrono::seconds(2)) {
            break;
        }
        if (!sleep(100)) {
            break;
        }
    }
    const int danger = vote.dangerous_row();
    LogInfo << "Sui talisman route: danger row " << danger << " upper votes " << vote.upper_votes << " lower votes "
            << vote.lower_votes;
    auto info = basic_info_with_what("SuiTalismanRoute");
    info["details"] = json::object { { "stage", m_stage_name },
                                     { "dangerous_row", danger },
                                     { "upper_votes", vote.upper_votes },
                                     { "lower_votes", vote.lower_votes } };
    callback(AsstMsg::SubTaskExtraInfo, info);
    if (danger == 0 && !last.empty()) {
        utils::save_debug_image(
            last,
            utils::path("debug") / "roguelike" / "talisman-route",
            true,
            "Sui unresolved opening route",
            "unknown");
    }
    return danger;
}

bool asst::RoguelikeBattleTaskPlugin::apply_jiegarden_talisman_route(int dangerous_row)
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || m_stage_name != "长驱不复") {
        return true;
    }
    const bool raidian_e2 = std::ranges::any_of(m_cur_deployment_opers, [&](const auto& oper) {
        return oper.name == "电弧" && !oper.cooling && m_oper_elite.contains(oper.name) &&
               m_oper_elite.at(oper.name) == 2 &&
               RoguelikeRecruit.get_oper_info(m_config->get_theme(), { oper.role, oper.name }).skill == 2;
    });
    if (!raidian_e2) {
        LogInfo << "Sui route formation bypassed: no confirmed E2 Raidian in deployed squad";
        return true;
    }
    // An uncertain observation never authorizes guessing the carry's safe row.
    if (dangerous_row != 2 && dangerous_row != 4) {
        pause();
        LogWarn << "Sui route unresolved: paused before deploying Raidian";
        m_task_ptr->set_enable(false);
        return false;
    }
    const int safe_row = dangerous_row == 2 ? 4 : 2;
    const auto plan = RoguelikeCopilot.get_stage_data("长驱不复_route_safe_" + std::to_string(safe_row));
    if (!plan || plan->deploy_plan.empty()) {
        pause();
        m_task_ptr->set_enable(false);
        return false;
    }
    m_deploy_plan = plan->deploy_plan;
    m_retreat_plan = plan->retreat_plan;
    // Prevent generic fallback from filling the row traversed by talismans.
    for (const int x : { 2, 4, 6, 8 }) {
        m_blacklist_location.insert({ x, dangerous_row });
    }
    LogInfo << "Sui route formation: safe row " << safe_row << " Raidian facing left; summons isolate retaliation";
    return true;
}

void asst::RoguelikeBattleTaskPlugin::wait_until_start_button_clicked()
{
    ProcessTask(*this, { m_config->get_theme() + "@Roguelike@WaitForStartButtonClicked" })
        .set_task_delay(0)
        .set_retry_times(0)
        .run();
}

bool asst::RoguelikeBattleTaskPlugin::calc_stage_info()
{
    LogTraceFunction;

    wait_until_start_button_clicked();
    clear();

    bool calced = false;

    const auto stage_name_task_ptr = Task.get("BattleStageName");
    sleep(stage_name_task_ptr->pre_delay);

    auto start = std::chrono::steady_clock::now();
    const auto timeout = std::chrono::seconds(Config.get_options().battle_start_timeout_seconds);

    while (std::chrono::steady_clock::now() - start < timeout) {
        if (need_exit()) {
            return false;
        }
        RegionOCRer name_analyzer(ctrler()->get_image());
        name_analyzer.set_task_info(stage_name_task_ptr);
        if (!name_analyzer.analyze()) {
            continue;
        }
        const std::string& text = name_analyzer.get_result().text;
        if (text.empty()) {
            continue;
        }

        static const std::vector<std::string> RoguelikeStageCode = { "ISW-NO",
                                                                     "ISW-DF",
                                                                     "ISW-DU",
                                                                     "ISW-SP",
                                                                     std::string() };
        TilePack::LevelKey stage_key;
        stage_key.name = text;

        for (const std::string& code : RoguelikeStageCode) {
            stage_key.code = code;
            if (!Tile.find(stage_key)) {
                continue;
            }
            calced = true;
            m_stage_name = text;
            m_map_data = TilePack::find_level(stage_key).value_or(Map::Level {});
            auto calc_result = TilePack::calc(m_map_data);
            m_normal_tile_info = std::move(calc_result.normal_tile_info);
            m_side_tile_info = std::move(calc_result.side_tile_info);
            m_retreat_button_pos = calc_result.retreat_button;
            m_skill_button_pos = calc_result.skill_button;
            break;
        }

        if (calced) {
            break;
        }
        std::this_thread::yield();
    }

    if (!calced) {
        callback(AsstMsg::SubTaskExtraInfo, basic_info_with_what("StageInfoError"));
        return false;
    }

    std::optional<CombatData> opt;
    if (m_config->get_mode() == RoguelikeMode::CLP_PDS) {
        opt = RoguelikeCopilot.get_stage_data(m_stage_name + "_collapse");
        if (opt == std::nullopt) {
            opt = RoguelikeCopilot.get_stage_data(m_stage_name);
        }
    }
    else {
        opt = RoguelikeCopilot.get_stage_data(m_stage_name);
    }

    if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
        const auto& status = m_config->status();
        const auto raidian = status.opers.find("电弧");
        const auto skill = status.selected_skills.find("电弧");
        if (raidian != status.opers.end() && skill != status.selected_skills.end() &&
            use_jiegarden_dark_arrows_s2_plan(m_stage_name, raidian->second.elite, skill->second)) {
            if (auto variant = RoguelikeCopilot.get_stage_data("暗箭难防_raidian_s2")) {
                opt = std::move(variant);
                auto info = basic_info_with_what("SuiStagePlanSelection");
                info["details"] = json::object { { "stage", m_stage_name },
                                                 { "plan", "暗箭难防_raidian_s2" },
                                                 { "raidian_elite", raidian->second.elite },
                                                 { "selected_skill", skill->second } };
                callback(AsstMsg::SubTaskExtraInfo, info);
            }
        }

        if (raidian != status.opers.end() && skill != status.selected_skills.end() &&
            use_jiegarden_boss_s1_plan(m_stage_name, raidian->second.elite, skill->second)) {
            if (auto variant = RoguelikeCopilot.get_stage_data("破岁阵祀_raidian_s1")) {
                opt = std::move(variant);
                LogInfo << "Sui boss plan: confirmed E2 Raidian with selected S1";
                auto info = basic_info_with_what("SuiBossPlanSelection");
                info["details"] = json::object { { "stage", m_stage_name },
                                                 { "plan", "破岁阵祀_raidian_s1" },
                                                 { "raidian_elite", raidian->second.elite },
                                                 { "selected_skill", skill->second } };
                callback(AsstMsg::SubTaskExtraInfo, info);
            }
        }
    }

    if (opt) {
        m_homes = opt->replacement_home;
        m_allow_to_use_dice = opt->use_dice_stage;
        m_blacklist_location = opt->blacklist_location;
        m_role_order = opt->role_order;
        m_force_deploy_direction = opt->force_deploy_direction;
        m_force_air_defense = AirDefenseData { .stop_blocking_deploy_num = opt->stop_deploy_blocking_num,
                                               .deploy_air_defense_num = opt->force_deploy_air_defense_num,
                                               .ban_medic = opt->force_ban_medic };
        m_deploy_plan = opt->deploy_plan;
        m_retreat_plan = opt->retreat_plan;
    }
    if (m_homes.empty()) {
        for (const auto& [loc, side] : m_normal_tile_info) {
            if (side.key == TilePack::TileKey::Home) {
                m_homes.emplace_back(ReplacementHome { loc, battle::DeployDirection::None });
            }
        }
        m_allow_to_use_dice = true;
        m_role_order = {
            battle::Role::Warrior, battle::Role::Pioneer, battle::Role::Medic,
            battle::Role::Tank,    battle::Role::Sniper,  battle::Role::Caster,
            battle::Role::Support, battle::Role::Special, battle::Role::Drone,
        };
    }
    else {
        auto homes_pos = m_homes | std::views::transform(&ReplacementHome::location);
        auto invalid_homes_pos =
            homes_pos |
            std::views::filter([&](const auto& home_pos) { return !m_normal_tile_info.contains(home_pos); }) |
            std::views::transform(&Point::to_string);
        if (!invalid_homes_pos.empty()) {
            Log.error("No replacement homes point:", invalid_homes_pos);
        }
        Log.info("replacement home:", homes_pos | std::views::transform(&Point::to_string));
    }

    if (m_homes.empty()) {
        Log.error("Unknown home pos");
        return false;
    }
    m_homes_status.resize(m_homes.size());

    auto cb_info = basic_info_with_what("StageInfo");
    auto& details = cb_info["details"];
    details["name"] = m_stage_name;
    details["size"] = m_side_tile_info.size();
    callback(AsstMsg::SubTaskExtraInfo, cb_info);

    return true;
}

asst::battle::OperPosition asst::RoguelikeBattleTaskPlugin::get_role_position(const battle::Role& role) const
{
    switch (role) {
    case battle::Role::Support:
    case battle::Role::Sniper:
    case battle::Role::Caster:
        return battle::OperPosition::AirDefense;
        break;
    case battle::Role::Pioneer:
    case battle::Role::Warrior:
    case battle::Role::Tank:
        return battle::OperPosition::Blocking;
        break;
    case battle::Role::Medic:
        return m_force_air_defense.ban_medic ? battle::OperPosition::None : battle::OperPosition::AirDefense;
        break;
    case battle::Role::Special:
    case battle::Role::Drone:
    default:
        return battle::OperPosition::None;
        break;
    }
}

void asst::RoguelikeBattleTaskPlugin::cache_oper_elite_status()
{
    const auto& oper_list = m_config->status().opers;
    for (const auto& oper : m_cur_deployment_opers) {
        m_oper_elite.emplace(oper.name, oper_list.contains(oper.name) ? oper_list.at(oper.name).elite : 0);
    }
}

void asst::RoguelikeBattleTaskPlugin::set_position_full(battle::LocationType loc_type, bool full)
{
    switch (loc_type) {
    case battle::LocationType::Melee:
        m_melee_full = full;
        break;
    case battle::LocationType::Ranged:
        m_ranged_full = full;
        break;
    case battle::LocationType::All:
        m_melee_full = full;
        m_ranged_full = full;
        break;
    case battle::LocationType::Invalid:
    case battle::LocationType::None:
    default:
        break;
    }
}

void asst::RoguelikeBattleTaskPlugin::set_position_full(const Point& loc, bool full)
{
    if (auto tile_iter = m_normal_tile_info.find(loc); tile_iter != m_normal_tile_info.end()) {
        set_position_full(tile_iter->second.buildable, full);
    }
}

void asst::RoguelikeBattleTaskPlugin::set_position_full(const battle::DeploymentOper& oper, bool full)
{
    set_position_full(BattleData.get_location_type(oper.role, oper.name), full);
}

bool asst::RoguelikeBattleTaskPlugin::get_position_full(battle::LocationType loc_type) const
{
    switch (loc_type) {
    case battle::LocationType::Melee:
        return m_melee_full;
        break;
    case battle::LocationType::Ranged:
        return m_ranged_full;
        break;
    case battle::LocationType::All:
        return m_melee_full && m_ranged_full;
        break;
    case battle::LocationType::Invalid:
    case battle::LocationType::None:
    default:
        break;
    }
    return false;
}

bool asst::RoguelikeBattleTaskPlugin::get_position_full(const battle::DeploymentOper& oper) const
{
    return get_position_full(BattleData.get_location_type(oper.role, oper.name));
}

bool asst::RoguelikeBattleTaskPlugin::do_best_deploy()
{
    LogTraceFunction;
    Log.info("m_kills", m_kills);

    // Expired opening positions must not reappear through generic fallback placement.
    if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
        for (const auto& [group, plans] : m_deploy_plan) {
            for (const auto& plan : plans) {
                if (m_kills <= plan.kill_upper_bound || m_blacklist_location.contains(plan.location)) {
                    continue;
                }
                if (expired_jiegarden_deploy_location(m_kills, plan.location, m_deploy_plan)) {
                    m_blacklist_location.insert(plan.location);
                    LogInfo << "Sui deployment window closed: tile " << plan.location << " kills " << m_kills;
                }
            }
        }
    }

    bool is_success = false;
    for (const auto& info : m_retreat_plan) {
        if (m_kills >= info.kill_lower_bound && m_kills <= info.kill_upper_bound) {
            if (m_used_tiles.contains(info.location)) {
                retreat_oper(info.location);
                Log.info("retreat operator");
                return true;
            }
        }
    }
    Log.debug("No operator needs to be retreated.");
    // 构造当前地图的部署指令列表
    std::vector<DeployPlanInfo> deploy_plan_list;
    // 获取当前肉鸽的分组信息[干员组1名称,干员组2名称,...]
    const auto& groups = RoguelikeRecruit.get_group_names(m_config->get_theme());
    // 获取当前肉鸽的分组内排名信息
    // const auto& group_rank = RoguelikeRecruit.get_group_rank(rogue_theme);
    for (const auto& oper : m_cur_deployment_opers) {
        // 干员冷却中
        if (oper.cooling) {
            LogDebug << "operator" << oper.name << "is cooling now.";
            continue;
        }

        const battle::OperNameTag oper_tag { oper.role, oper.name };
        // 获取招募信息
        const auto& recruit_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), oper_tag);
        // 获取会用到该干员的干员组[干员组1序号,干员组2序号,...]
        std::vector<int> group_ids = RoguelikeRecruit.get_group_ids_of_oper(m_config->get_theme(), oper_tag);

        bool is_in_group = false;
        for (const auto& group_id : group_ids) {
            // 当前干员组名,string类型
            std::string group_name = groups[group_id];
            LogDebug << m_stage_name << "group_name" << group_name;
            if (m_deploy_plan.contains(group_name)) {
                is_in_group = true;
                for (const auto& info : m_deploy_plan[group_name]) {
                    if (m_kills < info.kill_lower_bound || m_kills > info.kill_upper_bound) {
                        LogDebug << "    deploy info" << oper.name << "in group" << group_name << "is waiting.";
                        is_success = true; // 如果发现了待命干员，此函数最终返回true
                        continue;
                    }

                    DeployPlanInfo deploy_plan;
                    deploy_plan.role = oper.role;
                    deploy_plan.oper_name = oper.name;
                    // deploy_plan.oper_priority = recruit_info.recruit_priority;
                    // deploy_plan.oper_order_in_group = recruit_info.order_in_group.at(group_id);

                    deploy_plan.oper_order_in_group =
                        recruit_info.order_in_group.empty() ? INT_MAX : recruit_info.order_in_group.at(group_id);
                    deploy_plan.rank = info.rank;
                    deploy_plan.placed = info.location;
                    deploy_plan.direction = info.direction;
                    deploy_plan_list.emplace_back(deploy_plan);
                    LogDebug << "    deploy info" << deploy_plan.oper_name << "is No. "
                             << deploy_plan.oper_order_in_group + 1 << "in group" << group_name
                             << ", with deploy command rank" << deploy_plan.rank;
                }
            }
            else {
                LogDebug << m_stage_name << "group_name" << group_name << "operator" << oper.name
                         << "is not in the deploy plan.";
            }
        }
        if (!is_in_group) {
            LogTrace << m_stage_name << "operator" << oper.name << "is not in ALL deploy plan.";
        }
    }
    std::sort(deploy_plan_list.begin(), deploy_plan_list.end());
    const bool preferred_opening_pending =
        m_config->get_theme() == RoguelikeTheme::JieGarden &&
        !std::ranges::any_of(
            m_battlefield_opers,
            [](const auto& entry) { return jiegarden_opening_preference(entry.first.name) > 0; }) &&
        std::ranges::any_of(deploy_plan_list, [&](const auto& plan) {
            return jiegarden_opening_preference(plan.oper_name) > 0 && !m_used_tiles.contains(plan.placed) &&
                   !m_blacklist_location.contains(plan.placed);
        });
    for (const auto& deploy_plan : deploy_plan_list) {
        if (preferred_opening_pending && jiegarden_secondary_opener(deploy_plan.oper_name)) {
            LogTrace << "Defer secondary Sui opener for Raidian or Wisadel: " << deploy_plan.oper_name;
            continue;
        }
        if (!m_used_tiles.contains(deploy_plan.placed) &&
            !m_blacklist_location.contains(deploy_plan.placed) /* 判断该位置是否已被占据 */) {
            if (auto oper_it = std::ranges::find_if(
                    m_cur_deployment_opers,
                    [&](const auto& oper) {
                        return oper.role == deploy_plan.role && oper.name == deploy_plan.oper_name;
                    });
                oper_it == m_cur_deployment_opers.end() || !oper_it->available) { // 等费
                if (oper_it != m_cur_deployment_opers.end() && m_config->get_theme() == RoguelikeTheme::JieGarden &&
                    oper_it->role == Role::Drone && (oper_it->name == "赛柯" || oper_it->name == "Cycle") &&
                    oper_it->cost <= m_cost) {
                    // A summon quota or deployment limit can gray out Cycle even with enough DP.
                    // Keep its authored lane pending, but let a ready healer or blocker deploy.
                    LogTrace << "Defer unavailable Cycle with sufficient DP: " << oper_it->name << " cost "
                             << oper_it->cost << " DP " << m_cost;
                    continue;
                }
                LogTrace << "    best deploy is" << deploy_plan.oper_name << "with rank" << deploy_plan.rank
                         << "but now waiting for cost.";
                return true;
            }
            const bool accepted =
                deploy_oper(deploy_plan.role, deploy_plan.oper_name, deploy_plan.placed, deploy_plan.direction);
            battle::OperNameTag oper_tag { deploy_plan.role, deploy_plan.oper_name };
            // 防止滑动丢失(有些物体比如鸟笼没有方向),点一下右下角费用那里
            asst::BattleHelper::cancel_oper_selection();
            if (!confirm_deployment(accepted, deploy_plan.role, deploy_plan.oper_name, deploy_plan.placed)) {
                return true;
            }
            // 开始计时
            auto deployed_time = std::chrono::steady_clock::now();
            m_deployed_time.insert_or_assign(oper_tag, deployed_time);
            // 获取技能用法和使用次数
            const auto& oper_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), oper_tag);
            m_skill_usage[oper_tag] = oper_info.skill_usage;
            m_skill_times[oper_tag] = oper_info.skill_times;
            Log.trace("    best deploy is", deploy_plan.oper_name, "with rank", deploy_plan.rank);
            return true;
        }
    }
    return is_success;
}

bool asst::RoguelikeBattleTaskPlugin::confirm_deployment(
    bool accepted,
    battle::Role role,
    const std::string& name,
    const Point& location)
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || role == Role::Drone) {
        return accepted;
    }
    bool analyzed = accepted && update_deployment();
    auto in_hand = std::ranges::find_if(m_cur_deployment_opers, [&](const auto& oper) {
        return oper.role == role && oper.name == name;
    });
    if (accepted && analyzed && in_hand != m_cur_deployment_opers.end() && !in_hand->cooling) {
        // A slow emulator may still show the hand card during the placement animation.
        sleep(350);
        analyzed = update_deployment();
        in_hand = std::ranges::find_if(m_cur_deployment_opers, [&](const auto& oper) {
            return oper.role == role && oper.name == name;
        });
    }
    if (accepted && analyzed && in_hand == m_cur_deployment_opers.end()) {
        return true;
    }

    m_battlefield_opers.erase(battle::OperNameTag { role, name });
    m_used_tiles.erase(location);
    if (accepted && (!analyzed || in_hand->cooling)) {
        LogWarn << "Sui deployment has no active defender confirmation: " << name << " tile " << location
                << " analyzed " << analyzed;
        return false;
    }

    if (in_hand != m_cur_deployment_opers.end()) {
        LogWarn << "Sui rejected placement hand state: " << name << " tile " << location << " card cost "
                << in_hand->cost << " available " << in_hand->available;
    }
    const int failures = ++m_deploy_failure_counts[location];
    if (failures == 1 && try_clear_jiegarden_revenant(location)) {
        // The next normal deployment attempt must still confirm that the operator left the hand.
        // Keep the failure count so a respawn or unsuccessful retreat cannot cause an unbounded loop.
        return false;
    }
    const bool retry = retry_jiegarden_deploy(failures);
    if (!retry) {
        m_blacklist_location.insert(location);
    }
    LogWarn << "Sui deployment not confirmed: " << name << " tile " << location << " attempt " << failures
            << " retry same tile " << retry << " DP " << m_cost;
    const auto evidence = ctrler()->get_image();
    if (!evidence.empty()) {
        save_map(evidence);
    }
    return false;
}

bool asst::RoguelikeBattleTaskPlugin::try_clear_jiegarden_revenant(const Point& location)
{
    if (m_config->get_theme() != RoguelikeTheme::JieGarden || m_used_tiles.contains(location) ||
        m_revenant_clear_attempts.size() >= 4 || m_revenant_clear_attempts.contains(location) ||
        !std::ranges::any_of(m_battlefield_opers, [](const auto& entry) { return entry.first.name == "维什戴尔"; })) {
        return false;
    }
    m_revenant_clear_attempts.insert(location);
    cancel_oper_selection();
    if (need_exit() || !click_oper_on_battlefield(location)) {
        return false;
    }
    // W's automatically spawned tokens are absent from the hand and occupancy table.
    // A failed placement only authorizes inspection, never an unconditional retreat.
    for (int observation = 0; observation < 2; ++observation) {
        const auto image = ctrler()->get_image();
        if (need_exit() || image.empty() || analyze_detail_page_oper_name(image, battle::Role::Drone) != "魂灵之影") {
            cancel_oper_selection();
            LogInfo << "Sui blocked-tile recovery: no verified Revenant at" << location;
            return false;
        }
        if (observation == 0) {
            sleep(150);
        }
    }
    const auto evidence = ctrler()->get_image();
    utils::save_debug_image(
        evidence,
        utils::path("debug") / "roguelike" / "revenant-recovery",
        true,
        "Verified Revenant before retreat",
        m_stage_name);
    const bool sent = click_retreat();
    cancel_oper_selection();
    if (!sent) {
        return false;
    }
    sleep(250);
    set_position_full(location, false);
    LogInfo << "Sui blocked-tile recovery: verified Revenant retreat sent at" << location
            << "; retrying operator deployment with hand confirmation";
    return true;
}

bool asst::RoguelikeBattleTaskPlugin::do_once(const cv::Mat& image, const cv::Mat& image_prev)
{
    if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
        // Failed paused deployments can leave a valid battlefield with frozen DP and cooldowns.
        // Reuse the exact center-label gate and its recognized resume graph, never toggle blindly.
        OCRer paused(image);
        paused.set_task_info("LocalBattleUnpause");
        if (paused.analyze()) {
            LogWarn << "Sui idle frame is paused; running recognized battle resume";
            ProcessTask(*this, { "LocalBattleResume" }).set_retry_times(0).run();
            return true;
        }
    }
    check_drone_tiles();

    // TODO: move this to controller
    thread_local auto prev_frame_time = std::chrono::steady_clock::time_point {};
    static const auto min_frame_interval =
        std::chrono::milliseconds(Config.get_options().roguelike_fight_screencap_interval);

    // prevent our program from consuming too much CPU
    if (const auto now = std::chrono::steady_clock::now(); prev_frame_time > now - min_frame_interval) [[unlikely]] {
        Log.debug("Sleeping for framerate limit");
        std::this_thread::sleep_for(min_frame_interval - (now - prev_frame_time));
    }

    prev_frame_time = std::chrono::steady_clock::now();

    if (!m_first_deploy) {
        // Keep the pre-burst frame for retrospective chest/retaliation diagnosis.
        bool capture_w_burst = false;
        if (m_config->get_theme() == RoguelikeTheme::JieGarden && m_w_burst_evidence_count < 3) {
            for (const auto& [oper_tag, location] : m_battlefield_opers) {
                if (oper_tag.name != "维什戴尔") {
                    continue;
                }
                const auto usage = m_skill_usage.find(oper_tag);
                const bool automatic = usage != m_skill_usage.end() &&
                                       (usage->second == SkillUsage::Possibly || usage->second == SkillUsage::Times);
                capture_w_burst = automatic && is_skill_ready(location, image);
                break;
            }
        }
        const auto skill_time_before = m_last_use_skill_time;
        const bool used_skill = use_all_ready_skill(image);
        if (capture_w_burst) {
            for (const auto& [oper_tag, when] : m_last_use_skill_time) {
                const auto before = skill_time_before.find(oper_tag);
                if (oper_tag.name == "维什戴尔" && (before == skill_time_before.end() || before->second != when)) {
                    ++m_w_burst_evidence_count;
                    LogInfo << "Sui W pre-burst evidence: " << m_stage_name << " kills " << m_kills << " total "
                            << m_total_kills << " DP " << m_cost << " sample " << m_w_burst_evidence_count;
                    utils::save_debug_image(
                        image,
                        utils::path("debug") / "roguelike" / "w-bursts",
                        true,
                        "Sui pre-burst evidence",
                        m_stage_name,
                        "jpeg",
                        { cv::IMWRITE_JPEG_QUALITY, 90 });
                    break;
                }
            }
        }
        if (used_skill) {
            // Skills can add summon cards and shift every hand position. Observe a fresh frame before deploying.
            LogInfo << "Refreshing battle hand after skill activation";
            return true;
        }
    }

    std::unordered_set<std::string> pre_cooling;
    for (const auto& oper : m_cur_deployment_opers) {
        if (oper.cooling) {
            pre_cooling.emplace(oper.name);
            m_deployed_time.erase({ oper.role, oper.name });
        }
    }

    auto pre_battlefield = m_battlefield_opers;
    for (const auto& [oper_tag, loc] : pre_battlefield) {
        const auto& oper_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), oper_tag);
        auto iter = m_deployed_time.find(oper_tag);
        if (iter != m_deployed_time.end() && oper_info.auto_retreat > 0) {
            if (std::chrono::steady_clock::now() - m_deployed_time.at(oper_tag) >=
                oper_info.auto_retreat * std::chrono::seconds(1)) {
                // 时间到了就撤退
                if (asst::BattleHelper::retreat_oper(oper_tag.role, oper_tag.name)) {
                    m_deployed_time.erase(oper_tag);
                    // Retreat inserts a cooling card; the old frame no longer describes the hand.
                    return true;
                }
            }
        }
    }
    pre_battlefield = m_battlefield_opers;

    if (!update_deployment(false, image)) {
        return false;
    }
    update_cost(image, image_prev);
    update_kills(image, image_prev);

    std::unordered_set<std::string> cur_cooling;
    size_t cur_available_count = 0;   // without drones
    size_t cur_deployments_count = 0; // without drones
    for (const auto& oper : m_cur_deployment_opers) {
        if (oper.role == Role::Drone) {
            continue;
        }

        ++cur_deployments_count;
        if (oper.cooling) {
            cur_cooling.emplace(oper.name);
            m_deployed_time.erase({ oper.role, oper.name });
        }
        if (oper.available) {
            ++cur_available_count;
        }
    }

    if (do_best_deploy()) { // 这是新的部署逻辑，更加精确
        m_first_deploy = false;
        return true;
    }

    else { // 这是旧的、通用部署逻辑
        auto urgent_home_opt = check_urgent(pre_cooling, cur_cooling, pre_battlefield);

        battle::DeploymentOper best_oper;
        bool best_oper_is_dice = false;
        size_t normal_home_index = m_cur_home_index;
        if (!urgent_home_opt) {
            // 不要随便谁好了就上，等等费用，下点厉害的干员
            // TODO: 这个逻辑目前太简单了，待优化
            bool not_battlefield_too_few = m_battlefield_opers.size() > m_homes.size();
            bool available_too_few = cur_available_count <= cur_deployments_count / 2;
            bool not_too_many_cooling = cur_cooling.size() < cur_available_count;

            if (not_battlefield_too_few && available_too_few && not_too_many_cooling) {
                Log.info("wait a minute");
                return true;
            }
        }
        else {
            m_cur_home_index = *urgent_home_opt;

            if (m_allow_to_use_dice) {
                auto dice_key_iter = std::ranges::find_if(m_cur_deployment_opers, [&](const auto& oper) {
                    return DiceSet.contains(oper.name);
                });
                if (dice_key_iter != m_cur_deployment_opers.end()) {
                    best_oper_is_dice = true;
                    best_oper = *dice_key_iter;
                }
            }
        }

        Log.info("To path", m_cur_home_index);

        if (!update_deployment(false, image, true)) {
            return false;
        }

        if (!best_oper_is_dice) {
            if (auto best_oper_opt = calc_best_oper()) {
                best_oper = *best_oper_opt;
            }
            else {
                return true;
            }
        }

        // 计算最优部署位置及方向
        auto best_loc_opt = calc_best_loc(best_oper);
        if (!best_loc_opt) {
            Log.info("Tiles full while calc best plan.");
            set_position_full(best_oper, true);
            return true;
        }
        const auto& [placed_loc, direction] = *best_loc_opt;

        const bool accepted = deploy_oper(best_oper.role, best_oper.name, placed_loc, direction);
        if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
            cancel_oper_selection();
            if (!confirm_deployment(accepted, best_oper.role, best_oper.name, placed_loc)) {
                return true;
            }
        }
        postproc_of_deployment_conditions(best_oper, placed_loc, direction);

        battle::OperNameTag oper_tag { best_oper.role, best_oper.name };
        m_first_deploy = false;
        // 开始计时
        auto deployed_time = std::chrono::steady_clock::now();
        m_deployed_time.insert_or_assign(oper_tag, deployed_time);
        // 获取技能用法和使用次数
        const auto& oper_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), oper_tag);
        m_skill_usage[oper_tag] = oper_info.skill_usage;
        m_skill_times[oper_tag] = oper_info.skill_times;

        if (urgent_home_opt) {
            m_urgent_home_index.pop_front();
            m_cur_home_index = normal_home_index;
        }
        ++m_cur_home_index;
        if (m_cur_home_index >= m_homes.size()) {
            m_cur_home_index = 0;
        }
    }

    return true;
}

void asst::RoguelikeBattleTaskPlugin::postproc_of_deployment_conditions(
    const battle::DeploymentOper& oper,
    const Point& placed_loc,
    battle::DeployDirection direction)
{
    // 如果是医疗干员，判断覆盖范围内有无第一次放置的干员
    if (oper.role == battle::Role::Medic) {
        std::vector<size_t> contain_index;
        for (const Point& relative_pos : get_attack_range(oper, direction)) {
            Point absolute_pos = placed_loc + relative_pos;
            if (auto iter = m_blocking_for_home_index.find(absolute_pos); iter != m_blocking_for_home_index.end()) {
                m_homes_status[iter->second].wait_medic = false;
                contain_index.emplace_back(iter->second);
            }
        }
        if (!contain_index.empty()) {
            m_medic_for_home_index.emplace(placed_loc, std::move(contain_index));
        }

        m_homes_status[m_cur_home_index].wait_medic = false;
    }

    auto position = get_role_position(oper.role);
    switch (position) {
    case OperPosition::Blocking: {
        m_force_air_defense.has_deployed_blocking_num++;
        bool& wait_blocking = m_homes_status[m_cur_home_index].wait_blocking;
        if (wait_blocking) {
            wait_blocking = false;
            m_blocking_for_home_index.emplace(placed_loc, m_cur_home_index);
        }
    } break;
    case OperPosition::AirDefense:
        if (!m_force_air_defense.has_finished_deploy_air_defense) {
            m_force_air_defense.has_deployed_air_defense_num++;
            if (m_force_air_defense.has_deployed_air_defense_num >= m_force_air_defense.deploy_air_defense_num) {
                m_force_air_defense.has_finished_deploy_air_defense = true;
                Log.info("FORCE RANGED OPER DEPLOY END");
            }
        }
        break;
    default:
        break;
    }

    if (m_force_air_defense.has_finished_deploy_air_defense && position != OperPosition::AirDefense) {
        Log.info("FORCE RANGED OPER DEPLOY END");
        m_force_air_defense.has_finished_deploy_air_defense = true;
    }
}

// 将存在于场上超过限时的召唤物所在的地块重新设为可用
void asst::RoguelikeBattleTaskPlugin::check_drone_tiles()
{
    Time_Point now_time = std::chrono::system_clock::now();
    while ((!m_need_clear_tiles.empty()) && m_need_clear_tiles.top().placed_time < now_time) {
        const auto& placed_loc = m_need_clear_tiles.top().placed_loc;
        if (auto iter = m_used_tiles.find(placed_loc); iter != m_used_tiles.end()) {
            Log.info("Drone at location (", placed_loc.x, ",", placed_loc.y, ") is recognized as retreated");
            set_position_full(placed_loc, false);
            m_battlefield_opers.erase(iter->second);
            m_used_tiles.erase(iter);
        }
        m_need_clear_tiles.pop();
    }
}

std::optional<size_t> asst::RoguelikeBattleTaskPlugin::check_urgent(
    const std::unordered_set<std::string>& pre_cooling,
    const std::unordered_set<std::string>& cur_cooling,
    const std::map<battle::OperNameTag, Point>& pre_battlefield)
{
    std::vector<size_t> new_urgent;
    for (const auto& name : cur_cooling) {
        if (pre_cooling.find(name) != pre_cooling.cend()) {
            continue;
        }
        LogInfo << name << "retreated";
        auto pre_loc_iter =
            std::ranges::find_if(pre_battlefield, [&](const auto& pair) { return pair.first.name == name; });
        if (pre_loc_iter == pre_battlefield.cend()) {
            Log.error("the oper", name, "was not on the battlefield before");
            continue;
        }
        Point pre_loc = pre_loc_iter->second;

        if (auto del_loc_blocking = m_blocking_for_home_index.find(pre_loc);
            del_loc_blocking != m_blocking_for_home_index.end()) {
            Log.info("Urgent situation detected");

            size_t home_index = del_loc_blocking->second;
            m_homes_status[home_index].wait_blocking = true;
            new_urgent.emplace_back(home_index);
            m_blocking_for_home_index.erase(del_loc_blocking);
        }
        else if (
            auto del_loc_medic = m_medic_for_home_index.find(pre_loc); del_loc_medic != m_medic_for_home_index.end()) {
            for (const size_t& home_index : del_loc_medic->second) {
                m_homes_status[home_index].wait_medic = true;
            }
            m_medic_for_home_index.erase(del_loc_medic);
        }
        set_position_full(pre_loc, false);
    }

    // 同时出现了多个家门的紧急情况，index 序号小的是靠前的家门，优先入栈
    std::ranges::sort(new_urgent);
    for (const size_t& home_index : new_urgent) {
        if (std::ranges::find(m_urgent_home_index, home_index) != m_urgent_home_index.cend()) {
            continue;
        }
        m_urgent_home_index.emplace_back(home_index);
    }

    if (m_urgent_home_index.empty()) {
        return std::nullopt;
    }
    return m_urgent_home_index.front();
}

bool asst::RoguelikeBattleTaskPlugin::jiegarden_warmup_safe() const
{
    if (m_homes_status.empty() ||
        std::ranges::any_of(m_homes_status, [](const auto& home) { return home.wait_blocking; })) {
        return false;
    }
    // The Phalanx caster does not attack during S2 startup. Require an existing damage source.
    return std::ranges::any_of(m_battlefield_opers, [](const auto& entry) {
        const auto& tag = entry.first;
        return tag.role == Role::Sniper || (tag.role == Role::Warrior && tag.name != "玛恩纳") ||
               (tag.role == Role::Caster && tag.name != "圣聆初雪" && tag.name != "卡涅利安" && tag.name != "蜜蜡" &&
                tag.name != "薄绿" && tag.name != "林");
    });
}

std::optional<asst::battle::DeploymentOper> asst::RoguelikeBattleTaskPlugin::calc_best_oper() const
{
    // Cycle needs an authored firing lane; generic blocking and direction scoring are unsuitable.
    const auto needs_authored_plan = [&](const DeploymentOper& oper) {
        return m_config->get_theme() == RoguelikeTheme::JieGarden && oper.role == Role::Drone &&
               (oper.name == "赛柯" || oper.name == "Cycle");
    };
    bool has_medic = false;
    bool has_blocking = false;
    bool has_air_defense = false;
    for (const auto& oper : m_cur_deployment_opers) {
        if (needs_authored_plan(oper)) {
            continue;
        }
        const auto& role = oper.role;
        switch (role) {
        case Role::Medic:
            has_medic = true;
            break;
        default:
            break;
        }

        const auto& position = get_role_position(role);
        switch (position) {
        case OperPosition::Blocking:
            has_blocking = true;
            break;
        case OperPosition::AirDefense:
            has_air_defense = true;
            break;
        default:
            break;
        }

        // found all
        if (has_medic && has_blocking && has_air_defense) {
            break;
        }
    }

    bool use_air_defense =
        has_air_defense && !m_force_air_defense.has_finished_deploy_air_defense &&
        m_force_air_defense.has_deployed_blocking_num >= m_force_air_defense.stop_blocking_deploy_num && !m_ranged_full;
    bool use_blocking = has_blocking && m_homes_status[m_cur_home_index].wait_blocking && !m_melee_full;
    bool use_medic = has_medic && m_homes_status[m_cur_home_index].wait_medic && !m_ranged_full;
    Log.trace("use_air_defense", use_air_defense, ", use_blocking", use_blocking, ", use_medic", use_medic);

    if (m_config->get_theme() == RoguelikeTheme::JieGarden && m_battlefield_opers.empty() && !m_ranged_full) {
        const auto carry = jiegarden_opening_carry(
            m_cur_deployment_opers,
            [&](const auto& oper) { return jiegarden_opening_preference(oper.name) > 0 && !get_position_full(oper); },
            [](const auto& oper) { return jiegarden_opening_preference(oper.name); });
        if (carry) {
            const auto& oper = m_cur_deployment_opers[*carry];
            if (oper.available) {
                return oper;
            }
            LogTrace << "Reserve DP for preferred Sui opening carry: " << oper.name;
            return std::nullopt;
        }
    }

    if (m_config->get_theme() == RoguelikeTheme::JieGarden && use_air_defense &&
        m_force_air_defense.stop_blocking_deploy_num == 0 && m_battlefield_opers.empty()) {
        const auto carry = jiegarden_opening_carry(
            m_cur_deployment_opers,
            [&](const auto& oper) {
                return get_role_position(oper.role) == OperPosition::AirDefense &&
                       jiegarden_recruit_role(oper.name) == JieGardenRecruitRole::Core;
            },
            [&](const auto& oper) {
                return RoguelikeRecruit.get_oper_info(m_config->get_theme(), { oper.role, oper.name }).recruit_priority;
            });
        if (carry) {
            const auto& oper = m_cur_deployment_opers[*carry];
            if (oper.available) {
                return oper;
            }
            LogTrace << "Reserve DP for Sui opening carry: " << oper.name;
            return std::nullopt;
        }
    }

    if (m_config->get_theme() == RoguelikeTheme::JieGarden && !use_blocking && !use_medic && !m_ranged_full &&
        jiegarden_warmup_safe()) {
        const auto warmup = std::ranges::find_if(m_cur_deployment_opers, [&](const auto& oper) {
            return oper.name == "圣聆初雪" && !oper.cooling &&
                   RoguelikeRecruit.get_oper_info(m_config->get_theme(), { oper.role, oper.name }).skill == 2;
        });
        if (warmup != m_cur_deployment_opers.end()) {
            if (warmup->available) {
                LogTrace << "Sui protected lane: deploy Pramanix early for S2 startup";
                return *warmup;
            }
            LogTrace << "Sui protected lane: reserve DP for Pramanix S2 instead of auxiliary summons";
            return std::nullopt;
        }
    }

    std::vector<DeploymentOper> cur_available;
    for (const auto& oper : m_cur_deployment_opers) {
        if (oper.available && !needs_authored_plan(oper)) {
            cur_available.emplace_back(oper);
        }
    }
    // 费用高的优先用，放前面
    std::ranges::sort(cur_available, [](const auto& lhs, const auto& rhs) { return lhs.cost > rhs.cost; });

    DeploymentOper best_oper;

    for (auto role : m_role_order) {
        battle::OperPosition position = get_role_position(role);
        if (use_air_defense) {
            if (position != battle::OperPosition::AirDefense) {
                continue;
            }
        }
        else if (use_blocking) {
            if (position != battle::OperPosition::Blocking) {
                continue;
            }
        }
        else if (use_medic) {
            if (role != battle::Role::Medic) {
                continue;
            }
        }

        for (const battle::DeploymentOper& oper : cur_available) {
            if (oper.role == role && !DiceSet.contains(oper.name) && !get_position_full(oper)) {
                best_oper = oper;
                break;
            }
        }
        if (!best_oper.name.empty()) {
            break;
        }
    }
    if (best_oper.name.empty()) {
        Log.info("No best oper");
        return std::nullopt;
    }
    Log.info("best oper is", best_oper.name, "with cost being", best_oper.cost);
    return best_oper;
}

void asst::RoguelikeBattleTaskPlugin::all_melee_retreat()
{
    std::vector<Point> retreat_locs {};
    for (const auto& loc : m_used_tiles | std::views::keys) {
        auto& tile_info = m_normal_tile_info[loc];
        auto& type = tile_info.buildable;
        if (type == battle::LocationType::Melee || type == battle::LocationType::All) {
            retreat_locs.push_back(loc);
        }
    }
    for (const auto& loc : retreat_locs) {
        retreat_oper(loc);
    }
}

void asst::RoguelikeBattleTaskPlugin::clear()
{
    BattleHelper::clear();
    m_stage_name.clear();

    m_homes.clear();
    m_allow_to_use_dice = true;
    m_blacklist_location.clear();
    m_force_deploy_direction.clear();
    m_force_air_defense = decltype(m_force_air_defense)();

    m_cur_home_index = 0;
    m_first_deploy = true;
    m_deploy_failure_counts.clear();
    m_w_burst_evidence_count = 0;
    m_revenant_clear_attempts.clear();
    m_melee_full = false;
    m_ranged_full = false;
    m_homes_status.clear();
    m_blocking_for_home_index.clear();
    m_medic_for_home_index.clear();
    m_urgent_home_index = decltype(m_urgent_home_index)();
    m_need_clear_tiles = decltype(m_need_clear_tiles)();
    m_deploy_plan.clear();
    m_retreat_plan.clear();
    m_deployed_time.clear();

    m_oper_elite.clear();
}

std::vector<asst::Point> asst::RoguelikeBattleTaskPlugin::available_locations(const DeploymentOper& oper) const
{
    auto type = BattleData.get_location_type(oper.role, oper.name);
    if (type == LocationType::Invalid || type == LocationType::None) {
        return available_locations(get_role_usual_location(oper.role));
    }
    return available_locations(type);
}

std::vector<asst::Point> asst::RoguelikeBattleTaskPlugin::available_locations(battle::LocationType type) const
{
    std::vector<Point> result;
    for (const auto& [loc, tile] : m_normal_tile_info) {
        bool position_matched = tile.buildable == type || tile.buildable == battle::LocationType::All;
        position_matched |= (type == battle::LocationType::All) && (tile.buildable == battle::LocationType::Melee ||
                                                                    tile.buildable == battle::LocationType::Ranged);
        if (position_matched &&
            tile.key != TilePack::TileKey::DeepSea && // 水上要先放板子才能放人，肉鸽里也没板子，那就当作不可放置
            !m_used_tiles.contains(loc) && !m_blacklist_location.contains(loc)) {
            result.emplace_back(loc);
        }
    }
    return result;
}

asst::battle::AttackRange asst::RoguelikeBattleTaskPlugin::get_attack_range(
    const battle::DeploymentOper& oper,
    DeployDirection direction) const
{
    int64_t elite = 0;
    if (m_oper_elite.contains(oper.name)) {
        elite = m_oper_elite.at(oper.name);
    }
    battle::AttackRange right_attack_range = BattleData.get_range(oper.role, oper.name, elite);

    if (right_attack_range == BattleDataConfig::EmptyRange) {
        switch (oper.role) {
        case battle::Role::Support:
            right_attack_range = {
                Point(-1, -1), Point(0, -1), Point(1, -1), Point(2, -1), //
                Point(-1, 0),  Point(0, 0),  Point(1, 0),  Point(2, 0),  //
                Point(-1, 1),  Point(0, 1),  Point(1, 1),  Point(2, 1),  //
            };
            break;
        case battle::Role::Caster:
            right_attack_range = {
                Point(0, -1), Point(1, -1), Point(2, -1),              //
                Point(0, 0),  Point(1, 0),  Point(2, 0),  Point(3, 0), //
                Point(0, 1),  Point(1, 1),  Point(2, 1),               //
            };
            break;
        case battle::Role::Medic:
        case battle::Role::Sniper:
            right_attack_range = {
                Point(0, -1), Point(1, -1), Point(2, -1), Point(3, -1), //
                Point(0, 0),  Point(1, 0),  Point(2, 0),  Point(3, 0),  //
                Point(0, 1),  Point(1, 1),  Point(2, 1),  Point(3, 1),  //
            };
            break;
        case battle::Role::Warrior:
            right_attack_range = { Point(0, 0), Point(1, 0), Point(2, 0) };
            break;
        case battle::Role::Special:
        case battle::Role::Tank:
        case battle::Role::Pioneer:
        case battle::Role::Drone:
            right_attack_range = { Point(0, 0), Point(1, 0) };
            break;
        default:
            break;
        }
    }

    for (auto cur_direction :
         { DeployDirection::Right, DeployDirection::Up, DeployDirection::Left, DeployDirection::Down }) {
        if (cur_direction == direction) {
            break;
        }

        // rotate relative attack range counterclockwise
        for (Point& point : right_attack_range) {
            point = { point.y, -point.x };
        }
    }

    return right_attack_range;
}

std::optional<asst::RoguelikeBattleTaskPlugin::DeployInfo>
    asst::RoguelikeBattleTaskPlugin::calc_best_loc(const battle::DeploymentOper& oper) const
{
    size_t home_index = m_cur_home_index;
    if (home_index >= m_homes.size()) {
        Log.warn("home index is out of range", m_cur_home_index, m_homes.size());
        home_index = 0;
    }
    const ReplacementHome& home = m_homes[home_index];

    auto comp_dist = [&](const Point& lhs, const Point& rhs) -> bool {
        int lhs_y_dist = std::abs(lhs.y - home.location.y);
        int lhs_dist = std::abs(lhs.x - home.location.x) + lhs_y_dist;
        int rhs_y_dist = std::abs(rhs.y - home.location.y);
        int rhs_dist = std::abs(rhs.x - home.location.x) + rhs_y_dist;
        // 距离一样选择 x 轴上的，因为一般的地图都是横向的长方向
        return lhs_dist == rhs_dist ? lhs_y_dist < rhs_y_dist : lhs_dist < rhs_dist;
    };
    std::vector<Point> available_loc = available_locations(oper);
    if (available_loc.empty()) {
        Log.error("No available locations");
        return std::nullopt;
    }
    // 把所有可用的点按距离排个序
    std::ranges::sort(available_loc, comp_dist);

    if (DiceSet.contains(oper.name)) {
        return DeployInfo { available_loc.back(), DeployDirection::None };
    }

    Point best_location;
    DeployDirection best_direction = DeployDirection::None;
    int max_score = INT_MIN;

    const auto& near_loc = available_loc.front();
    int min_dist = std::abs(near_loc.x - home.location.x) + std::abs(near_loc.y - home.location.y);

    // 取距离最近的N个点，计算分数。然后使用得分最高的点
    constexpr int CalcPointCount = 4;
    const size_t candidate_count = oper.role == battle::Role::Medic ? available_loc.size() : CalcPointCount;
    for (const auto& loc : available_loc | std::views::take(candidate_count)) {
        const auto& [cur_direction, cur_score] = calc_best_direction_and_score(loc, oper, home.direction);
        // 离得远的要扣分
        constexpr int DistWeights = -1050;
        int extra_dist = std::abs(loc.x - home.location.x) + std::abs(loc.y - home.location.y) - min_dist;
        int extra_dist_score = DistWeights * extra_dist;
        if (oper.role == battle::Role::Medic) { // 医疗干员离得远无所谓
            extra_dist_score = 0;
        }

        if (cur_score + extra_dist_score > max_score) {
            max_score = cur_score + extra_dist_score;
            best_location = loc;
            best_direction = cur_direction;
        }
    }

    // 强制变化为确定的攻击方向
    if (auto iter = m_force_deploy_direction.find(best_location); iter != m_force_deploy_direction.end()) {
        if (iter->second.role.contains(oper.role)) {
            best_direction = iter->second.direction;
        }
    }

    return DeployInfo { best_location, best_direction };
}

asst::RoguelikeBattleTaskPlugin::DirectionAndScore asst::RoguelikeBattleTaskPlugin::calc_best_direction_and_score(
    Point loc,
    const battle::DeploymentOper& oper,
    DeployDirection recommended_direction) const
{
    LogTraceFunction;

    size_t home_index = m_cur_home_index;
    if (home_index >= m_homes.size()) {
        Log.warn("home index is out of range", m_cur_home_index, m_homes.size());
        home_index = 0;
    }
    Point home_loc = m_homes[home_index].location;

    DeployDirection base_direction = DeployDirection::None;
    if (loc.x == home_loc.x) {
        if (loc.y - home_loc.y >= 0) {
            base_direction = DeployDirection::Up;
        }
        else {
            base_direction = DeployDirection::Down;
        }
    }
    else {
        if (loc.x - home_loc.x >= 0) {
            base_direction = DeployDirection::Right;
        }
        else {
            base_direction = DeployDirection::Left;
        }
    }

    // 家门反过来
    DeployDirection home_direction = DeployDirection::None;
    switch (base_direction) {
    case DeployDirection::Right:
        home_direction = DeployDirection::Left;
        break;
    case DeployDirection::Up:
        home_direction = DeployDirection::Down;
        break;
    case DeployDirection::Left:
        home_direction = DeployDirection::Right;
        break;
    case DeployDirection::Down:
        home_direction = DeployDirection::Up;
        break;
    default:
        break;
    }

    // 医疗优先朝向家门
    if (oper.role == battle::Role::Medic) {
        base_direction = home_direction;
    }

    int max_score = 0;
    DeployDirection best_direction = DeployDirection::None;

    for (auto direction :
         { DeployDirection::Right, DeployDirection::Up, DeployDirection::Left, DeployDirection::Down }) {
        int score = 0;
        // 按朝右算，后面根据方向做转换
        for (const Point& relative_pos : get_attack_range(oper, direction)) {
            Point absolute_pos = loc + relative_pos;

            using TileKey = TilePack::TileKey;
            // 战斗干员朝向的权重
            static const std::unordered_map<TileKey, int> TileKeyFightWeights = {
                { TileKey::Invalid, 0 },    { TileKey::Forbidden, 0 },  { TileKey::Wall, 500 },
                { TileKey::Road, 1000 },    { TileKey::Home, 500 },     { TileKey::EnemyHome, 1000 },
                { TileKey::Green, 0 },      { TileKey::Airport, 1000 }, { TileKey::Floor, 1000 },
                { TileKey::Hole, 0 },       { TileKey::Telin, 700 },    { TileKey::Telout, 800 },
                { TileKey::Grass, 500 },    { TileKey::DeepSea, 1000 }, { TileKey::Volcano, 1000 },
                { TileKey::Healing, 1000 }, { TileKey::Fence, 800 },    { TileKey::Infection, 100 },
            };
            // 治疗干员朝向的权重
            static const std::unordered_map<TileKey, int> TileKeyMedicWeights = {
                { TileKey::Invalid, 0 },    { TileKey::Forbidden, 0 }, { TileKey::Wall, 1000 },
                { TileKey::Road, 1000 },    { TileKey::Home, 0 },      { TileKey::EnemyHome, 0 },
                { TileKey::Green, 0 },      { TileKey::Airport, 0 },   { TileKey::Floor, 0 },
                { TileKey::Hole, 0 },       { TileKey::Telin, 0 },     { TileKey::Telout, 0 },
                { TileKey::Grass, 500 },    { TileKey::DeepSea, 0 },   { TileKey::Volcano, 1000 },
                { TileKey::Healing, 1000 }, { TileKey::Fence, 1000 },  { TileKey::Infection, 1000 },
            };

            switch (oper.role) {
            case battle::Role::Medic:
                if (auto iter = m_used_tiles.find(absolute_pos);
                    iter != m_used_tiles.cend() &&
                    iter->second.role != battle::Role::Drone) { // 根据哪个方向上人多决定朝向哪
                    score += 100'000;
                }
                if (auto iter = m_side_tile_info.find(absolute_pos); iter == m_side_tile_info.end()) {
                }
                else if (auto it = TileKeyMedicWeights.find(iter->second.key); it != TileKeyMedicWeights.end()) {
                    score += it->second;
                }
                break;
            default:
                if (auto iter = m_side_tile_info.find(absolute_pos); iter == m_side_tile_info.end()) {
                }
                else if (auto it = TileKeyFightWeights.find(iter->second.key); it != TileKeyFightWeights.end()) {
                    score += it->second;
                }
                break;
            }
        }

        if (direction == base_direction) {
            score += 300;
        }
        if (oper.role != battle::Role::Medic && direction == home_direction) {
            score -= 500;
        }
        if (oper.role != battle::Role::Medic && direction == recommended_direction) {
            score += 2000;
        }
        if (score > max_score) {
            max_score = score;
            best_direction = direction;
        }
    }

    return { best_direction, max_score };
}
