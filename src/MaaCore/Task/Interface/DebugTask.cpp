#include "DebugTask.h"

#include "Task/Miscellaneous/BattleFormationTask.h"

#include "MaaUtils/Encoding.h"
#include <boost/regex.hpp>
#include <filesystem>
#include <shared_mutex>

#include "Common/AsstMsg.h"
#include "Common/AsstTypes.h"
#include "Config/Miscellaneous/BattleDataConfig.h"
#include "Config/Miscellaneous/TilePack.h"
#include "Config/TaskData.h"
#include "Config/TemplResource.h"
#include "MaaUtils/ImageIo.h"
#include "MaaUtils/NoWarningCV.hpp"
#include "Utils/Logger.hpp"
#include "Vision/Battle/BattlefieldClassifier.h"
#include "Vision/Battle/BattlefieldMatcher.h"
#include "Vision/BestMatcher.h"
#include "Vision/FeatureMatcher.h"
#include "Vision/Matcher.h"
#include "Vision/Miscellaneous/DepotImageAnalyzer.h"
#include "Vision/Miscellaneous/PipelineAnalyzer.h"
#include "Vision/Miscellaneous/StageDropsImageAnalyzer.h"
#include "Vision/MultiMatcher.h"
#include "Vision/OCRer.h"
#include "Vision/RegionOCRer.h"
#include "Vision/Roguelike/RoguelikeSkillSelectionImageAnalyzer.h"

MAA_SUPPRESS_CV_WARNINGS_BEGIN
#include <Arknights-Tile-Pos/TileCalc2.hpp>
MAA_SUPPRESS_CV_WARNINGS_END

asst::DebugTask::DebugTask(const AsstCallback& callback, Assistant* inst) :
    InterfaceTask(callback, inst, TaskType)
{
}

bool asst::DebugTask::run()
{
    // PackageTask::run 被覆盖，运行标记须自行置位，set_params 据此拒绝运行中更新
    m_running = true;

    if (m_image_test_mode == "tile_projection") {
        return image_test_tile_projection();
    }
    if (m_image_test_mode == "formation_operators") {
        return image_test_formation_operators();
    }
    if (m_image_test_mode == "battle_deployment") {
        return image_test_battle_deployment();
    }
    if (m_image_test_mode == "roguelike_skills") {
        return image_test_roguelike_skills();
    }
    if (m_image_test_mode == "report") {
        return image_test_report();
    }
    if (m_image_test_mode == "pipeline") {
        return image_test_pipeline();
    }
    if (m_image_test_mode == "ocr") {
        return image_test_ocr();
    }
    if (m_image_test_mode == "templ") {
        return image_test_templ();
    }
    return true;
}

// 读取本地图片并缩放到 1280x720（INTER_AREA），与线上 Controller::get_resized_image_cache 一致；
// 需要其他评估尺寸（如仓库识别的 1066x599）的先经此归一，再用 resize_eval_image 二级缩放
std::optional<cv::Mat> asst::DebugTask::load_eval_image(const std::string& utf8_path)
{
    cv::Mat image = MAA_NS::imread(asst::utils::path(utf8_path));
    if (image.empty()) {
        LogError << __FUNCTION__ << "failed to load image:" << utf8_path;
        return std::nullopt;
    }
    if (image.cols * 9 != image.rows * 16) {
        // 线上遇到非 16:9 截图会直接报 Unsupported resolution，这里拉伸后仍可评估，
        // 但结果与该分辨率的线上行为没有可比性
        LogWarn << __FUNCTION__ << "image is not 16:9, will be stretched to 1280x720:" << utf8_path;
    }
    if (image.cols != 1280 || image.rows != 720) {
        cv::resize(image, image, { 1280, 720 }, 0, 0, cv::INTER_AREA);
    }
    return image;
}

// 归一后的二级缩放（INTER_AREA），复刻线上各识别器在 720p 截图基础上的尺度预处理
cv::Mat asst::DebugTask::resize_eval_image(cv::Mat image, int width, int height)
{
    if (image.cols != width || image.rows != height) {
        cv::resize(image, image, { width, height }, 0, 0, cv::INTER_AREA);
    }
    return image;
}

json::object
    asst::DebugTask::to_result_json(const std::string& task_name, const asst::PipelineAnalyzer::ResultOpt& result_opt)
{
    json::object result { { "task", task_name } };
    if (!result_opt) {
        result["hit"] = false;
        return result;
    }
    result["hit"] = true;
    // JustReturn 任务无识别结果（variant 默认构造的 Matcher::Result），带上算法类型供调用方区分
    result["algorithm"] = asst::enum_to_string(result_opt->task_ptr->algorithm);
    const auto& result_var = result_opt->result;
    if (std::holds_alternative<asst::Matcher::Result>(result_var)) {
        const auto& r = std::get<asst::Matcher::Result>(result_var);
        result["score"] = r.score;
        result["templ"] = r.templ_name;
    }
    else if (std::holds_alternative<asst::OCRer::Result>(result_var)) {
        const auto& r = std::get<asst::OCRer::Result>(result_var);
        result["score"] = r.score;
        result["text"] = r.text;
    }
    else if (std::holds_alternative<asst::FeatureMatcher::Result>(result_var)) {
        // FeatureMatch 的判据是特征点数而非相似度分数
        const auto& r = std::get<asst::FeatureMatcher::Result>(result_var);
        result["count"] = r.count;
    }
    result["rect"] = (json::value)result_opt->rect;
    return result;
}

// 离线图片评估的参数协议（AsstAppendTask 的 params，type 固定为 "Debug"）。
// 日常用配套的 python 驱动 tools/maa_core_eval.py 调用，无需手拼 json：
// { "mode": "report" | "pipeline" | "ocr" | "templ", "images": [图片路径], "tasks": [任务名],
//   "templates": [模板名], "task": "任务名", "roi": [x, y, w, h], "threshold": 0.8, "resize": [w, h] }
// images/tasks/templates 为 UTF-8 路径与名字（模板名也接受绝对路径图片文件）；roi 仅 ocr/templ
// 模式使用，缺省全图；task 仅 templ 模式使用（mask/method/roi 等 Matcher 配置取自该任务，
// 显式传 roi 可覆盖任务 roi；未显式给 threshold 时 hit 判定也取该任务阈值）；threshold/resize
// 仅 templ 模式使用（内部匹配放开阈值恒报最佳得分；resize 为 1280x720 归一后的二级 INTER_AREA
// 缩放尺寸，复刻线上识别器的尺度预处理）
bool asst::DebugTask::set_params(const json::value& params)
{
    LogTraceFunction;

    // AsstSetTaskParams 在任务运行中调用会与 run() 遍历 m_eval_* 产生数据竞争，运行中拒绝更新
    if (m_running) {
        LogError << __FUNCTION__ << "failed, task is running";
        return false;
    }

    // 畸形参数（如 roi/resize 数组里有非数字）会让 as_integer 抛异常，不能让它穿过 C 接口
    try {
        return set_params_impl(params);
    }
    catch (const std::exception& e) {
        LogError << __FUNCTION__ << "failed, invalid params:" << e.what();
        return false;
    }
}

bool asst::DebugTask::set_params_impl(const json::value& params)
{
    auto mode = params.get("mode", "");
    if (mode.empty()) {
        return true; // 无 mode 的 Debug 任务保持 run() 空跑的旧行为
    }

    // 全部解析校验通过后才写成员，AsstSetTaskParams 更新失败时任务保持原有完整参数
    std::vector<std::string> images;
    std::vector<std::string> stages;
    std::vector<std::string> tasks;
    std::vector<std::string> templates;
    std::string templ_task;
    Rect roi;
    double threshold = TemplThresholdDefault;
    std::optional<std::pair<int, int>> resize;

    if (mode == "tile_projection") {
        auto stages_opt = params.find<std::vector<std::string>>("stages");
        if (!stages_opt || stages_opt->empty() || stages_opt->size() > 16 ||
            std::ranges::any_of(*stages_opt, [](const auto& stage) { return stage.empty() || stage.size() > 128; })) {
            LogError << __FUNCTION__ << "failed, invalid stage IDs";
            return false;
        }
        stages = std::move(*stages_opt);
    }
    else {
        auto images_opt = params.find<std::vector<std::string>>("images");
        if (!images_opt || images_opt->empty()) {
            LogError << __FUNCTION__ << "failed, images not found";
            return false;
        }
        images = std::move(*images_opt);
    }

    if (mode == "report" || mode == "pipeline") {
        auto tasks_opt = params.find<std::vector<std::string>>("tasks");
        if (!tasks_opt || tasks_opt->empty()) {
            LogError << __FUNCTION__ << "failed, tasks not found";
            return false;
        }
        for (auto& task : *tasks_opt) {
            if (Task.get(task) == nullptr) {
                LogError << __FUNCTION__ << "failed, task not found:" << task;
                return false;
            }
            tasks.emplace_back(std::move(task));
        }
    }
    else if (mode == "ocr" || mode == "templ") {
        if (params.contains("roi")) {
            // 畸形 roi（如只给了三个数）不能静默退化成全图，诊断工具须显式报错
            auto roi_opt = params.find<asst::Rect>("roi");
            if (!roi_opt) {
                LogError << __FUNCTION__ << "failed, invalid roi";
                return false;
            }
            roi = *roi_opt;
        }
        if (mode == "templ") {
            auto templates_opt = params.find<std::vector<std::string>>("templates");
            if (!templates_opt || templates_opt->empty()) {
                LogError << __FUNCTION__ << "failed, templates not found";
                return false;
            }
            for (const auto& templ : *templates_opt) {
                templates.emplace_back(templ);
            }
            if (auto task_opt = params.find<std::string>("task"); task_opt) {
                // Matcher 配置只能取自模板类任务；Task.get<MatchTaskInfo> 对非 MatchTaskInfo
                // 任务返回空，后续 set_task_info 会对其解引用，必须在入口拒绝
                auto match_ptr = Task.get<MatchTaskInfo>(*task_opt);
                if (match_ptr == nullptr) {
                    LogError << __FUNCTION__ << "failed, task not found or not a match task:" << *task_opt;
                    return false;
                }
                templ_task = *task_opt;
                double default_threshold =
                    !match_ptr->templ_thresholds.empty() ? match_ptr->templ_thresholds.front() : TemplThresholdDefault;
                threshold = params.get("threshold", default_threshold);
            }
            else {
                threshold = params.get("threshold", TemplThresholdDefault);
            }
            if (auto resize_opt = params.find<std::array<int, 2>>("resize"); resize_opt) {
                int resize_w = (*resize_opt)[0];
                int resize_h = (*resize_opt)[1];
                if (resize_w <= 0 || resize_h <= 0) {
                    LogError << __FUNCTION__ << "failed, invalid resize:" << resize_w << resize_h;
                    return false;
                }
                resize = std::make_pair(resize_w, resize_h);
            }
        }
    }
    else if (
        mode == "roguelike_skills" || mode == "battle_deployment" || mode == "formation_operators" ||
        mode == "tile_projection") {
        // Runs the actual formation skill analyzer without connecting to a device.
    }
    else {
        LogError << __FUNCTION__ << "failed, unknown mode:" << mode;
        return false;
    }

    m_eval_formation_prefix = params.get("task_prefix", "");
    if (!m_eval_formation_prefix.empty() &&
        (mode != "formation_operators" || m_eval_formation_prefix != "SandRoster@")) {
        LogError << __FUNCTION__ << "Unsupported offline formation layout prefix";
        return false;
    }
    m_image_test_mode = std::move(mode);
    m_eval_images = std::move(images);
    m_eval_stages = std::move(stages);
    m_eval_tasks = std::move(tasks);
    m_eval_templates = std::move(templates);
    m_eval_templ_task = std::move(templ_task);
    m_eval_roi = roi;
    m_eval_threshold = threshold;
    m_eval_resize = resize;
    return true;
}

void asst::DebugTask::emit_eval_error(const std::string& mode, const std::string& image_path, const std::string& error)
{
    LogError << __FUNCTION__ << image_path << error;
    callback(
        AsstMsg::SubTaskExtraInfo,
        json::object { { "what", "DebugImageTest" },
                       { "details", json::object { { "mode", mode }, { "image", image_path }, { "error", error } } } });
}

bool asst::DebugTask::image_test_formation_operators()
{
    bool all_ok = true;
    for (const auto& path : m_eval_images) {
        auto image = load_eval_image(path);
        if (!image) {
            all_ok = false;
            emit_eval_error("formation_operators", path, "failed to load image");
            continue;
        }
        const auto recognized = BattleFormationTask::analyzer_opers(*image, m_eval_formation_prefix);
        json::array operators;
        for (const auto& oper : recognized) {
            const auto [elite, level] =
                BattleQuickFormation::analyze_oper_level(*image, oper.flag_rect, m_eval_formation_prefix);
            json::array character_ids;
            for (const auto& id : BattleData.get_ids(oper.role, oper.text)) {
                character_ids.emplace_back(id);
            }
            operators.emplace_back(
                json::object {
                    { "character_ids", std::move(character_ids) },
                    { "name", oper.text },
                    { "name_score", oper.score },
                    { "role", static_cast<int>(oper.role) },
                    { "selected", oper.is_selected },
                    { "elite", elite },
                    { "level", level },
                    { "rect", json::array { oper.rect.x, oper.rect.y, oper.rect.width, oper.rect.height } },
                    { "flag_rect",
                      json::array { oper.flag_rect.x, oper.flag_rect.y, oper.flag_rect.width, oper.flag_rect.height } },
                    { "flag_score", oper.flag_score } });
        }
        callback(
            AsstMsg::SubTaskExtraInfo,
            json::object { { "what", "DebugImageTest" },
                           { "details",
                             json::object { { "mode", "formation_operators" },
                                            { "task_prefix", m_eval_formation_prefix },
                                            { "image", path },
                                            { "hit", !recognized.empty() },
                                            { "operators", std::move(operators) },
                                            { "elite_zero_may_be_template_miss", true },
                                            { "inputs_issued", false } } } });
    }
    return all_ok;
}

bool asst::DebugTask::image_test_battle_deployment()
{
    bool all_ok = true;
    for (const auto& path : m_eval_images) {
        auto image = load_eval_image(path);
        if (!image) {
            all_ok = false;
            emit_eval_error("battle_deployment", path, "failed to load image");
            continue;
        }
        BattlefieldMatcher analyzer(*image);
        BattlefieldMatcher::ObjectOfInterest interest;
        interest.deployment = true;
        interest.oper_cost = true;
        interest.costs = true;
        analyzer.set_object_of_interest(interest);
        auto result = analyzer.analyze();
        json::array operators;
        if (result) {
            for (const auto& oper : result->deployment) {
                operators.emplace_back(
                    json::object {
                        { "index", oper.index },
                        { "role", static_cast<int>(oper.role) },
                        { "cost", oper.cost },
                        { "available", oper.available },
                        { "cooling", oper.cooling },
                        { "rect", json::array { oper.rect.x, oper.rect.y, oper.rect.width, oper.rect.height } } });
            }
        }
        callback(
            AsstMsg::SubTaskExtraInfo,
            json::object { { "what", "DebugImageTest" },
                           { "details",
                             json::object { { "mode", "battle_deployment" },
                                            { "image", path },
                                            { "hit", result.has_value() },
                                            { "dp", result ? result->costs.value : -1 },
                                            { "operators", std::move(operators) } } } });
    }
    return all_ok;
}

bool asst::DebugTask::image_test_roguelike_skills()
{
    bool all_ok = true;
    for (const auto& path : m_eval_images) {
        auto image = load_eval_image(path);
        if (!image) {
            all_ok = false;
            emit_eval_error("roguelike_skills", path, "failed to load image");
            continue;
        }
        RoguelikeSkillSelectionImageAnalyzer analyzer(*image);
        const bool hit = analyzer.analyze();
        json::array rows;
        for (const auto& [name, skills] : analyzer.get_result()) {
            json::array rects;
            for (const auto& rect : skills) {
                rects.emplace_back(json::array { rect.x, rect.y, rect.width, rect.height });
            }
            rows.emplace_back(json::object { { "name", name }, { "skills", std::move(rects) } });
        }
        callback(
            AsstMsg::SubTaskExtraInfo,
            json::object { { "what", "DebugImageTest" },
                           { "details",
                             json::object { { "mode", "roguelike_skills" },
                                            { "image", path },
                                            { "hit", hit },
                                            { "rows", std::move(rows) } } } });
    }
    return all_ok;
}

bool asst::DebugTask::image_test_report()
{
    bool all_ok = true;
    for (const auto& image_path : m_eval_images) {
        try {
            auto image_opt = load_eval_image(image_path);
            if (!image_opt) {
                all_ok = false;
                emit_eval_error("report", image_path, "failed to load image");
                continue;
            }

            json::array results;
            for (const auto& task_name : m_eval_tasks) {
                PipelineAnalyzer analyzer(*image_opt, Rect(), nullptr);
                analyzer.set_tasks({ task_name });
                auto result_opt = analyzer.analyze();

                json::object result = to_result_json(task_name, result_opt);
                LogInfo << __FUNCTION__ << image_path << task_name << (result_opt ? "hit" : "miss") << result.dumps();
                results.emplace_back(std::move(result));
            }

            callback(
                AsstMsg::SubTaskExtraInfo,
                json::object { { "what", "DebugImageTest" },
                               { "details",
                                 json::object { { "mode", "report" },
                                                { "image", image_path },
                                                { "results", std::move(results) } } } });
        }
        catch (const std::exception& e) {
            // ASST_DEBUG 下模板缺失/为空等会 throw，逐图兜住避免后续图静默缺结果
            all_ok = false;
            emit_eval_error("report", image_path, e.what());
        }
    }
    return all_ok;
}

bool asst::DebugTask::image_test_pipeline()
{
    bool all_ok = true;
    for (const auto& image_path : m_eval_images) {
        try {
            auto image_opt = load_eval_image(image_path);
            if (!image_opt) {
                all_ok = false;
                emit_eval_error("pipeline", image_path, "failed to load image");
                continue;
            }

            PipelineAnalyzer analyzer(*image_opt, Rect(), nullptr);
            analyzer.set_tasks(m_eval_tasks);
            auto result_opt = analyzer.analyze();

            json::object detail { { "mode", "pipeline" }, { "image", image_path } };
            json::array next;
            if (result_opt) {
                // 任务名须嵌在 result 内上报：平铺到 details.task 会被 AbstractTask::callback 按 @ 截断
                const auto result = to_result_json(result_opt->task_ptr->name, result_opt);
                detail["hit"] = true;
                detail["result"] = result;
                for (const auto& next_task : result_opt->task_ptr->next) {
                    next.emplace_back(next_task);
                }
                LogInfo << __FUNCTION__ << image_path << "hit" << result.dumps();
            }
            else {
                detail["hit"] = false;
                LogInfo << __FUNCTION__ << image_path << "miss";
            }
            detail["next"] = std::move(next);

            callback(
                AsstMsg::SubTaskExtraInfo,
                json::object { { "what", "DebugImageTest" }, { "details", std::move(detail) } });
        }
        catch (const std::exception& e) {
            all_ok = false;
            emit_eval_error("pipeline", image_path, e.what());
        }
    }
    return all_ok;
}

bool asst::DebugTask::image_test_ocr()
{
    bool all_ok = true;
    for (const auto& image_path : m_eval_images) {
        try {
            auto image_opt = load_eval_image(image_path);
            if (!image_opt) {
                all_ok = false;
                emit_eval_error("ocr", image_path, "failed to load image");
                continue;
            }

            // 不 set_task_info：默认参数下 required 为空即不做 expected 过滤、不做 ocrReplace，
            // 返回 OCR 引擎的原始识别结果；带任务配置的评估用 report 模式
            OCRer analyzer(*image_opt, m_eval_roi); // 空 roi 由 VisionHelper 展开为全图
            auto results_opt = analyzer.analyze();

            json::array results;
            if (results_opt) {
                for (const auto& res : *results_opt) {
                    results.emplace_back(
                        json::object { { "text", res.text },
                                       { "score", res.score },
                                       { "rect", (json::value)(res.rect) } });
                }
            }
            LogInfo << __FUNCTION__ << image_path << "ocr" << results.dumps();

            callback(
                AsstMsg::SubTaskExtraInfo,
                json::object { { "what", "DebugImageTest" },
                               { "details",
                                 json::object { { "mode", "ocr" },
                                                { "image", image_path },
                                                { "results", std::move(results) } } } });
        }
        catch (const std::exception& e) {
            all_ok = false;
            emit_eval_error("ocr", image_path, e.what());
        }
    }
    return all_ok;
}

bool asst::DebugTask::image_test_templ()
{
    bool all_ok = true;
    for (const auto& image_path : m_eval_images) {
        try {
            auto image_opt = load_eval_image(image_path);
            if (image_opt && m_eval_resize) {
                *image_opt = resize_eval_image(std::move(*image_opt), m_eval_resize->first, m_eval_resize->second);
            }
            if (!image_opt) {
                all_ok = false;
                emit_eval_error("templ", image_path, "failed to load image");
                continue;
            }

            json::array results;
            for (const auto& templ_name : m_eval_templates) {
                // 模板名与 core 各处 get_templ 一致：物品 ID（如 "2001"）或相对
                // resource/template 的路径（如 "items/2001.png"）；也接受绝对路径的
                // 图片文件（调用方自行预处理过的模板）
                Matcher analyzer(*image_opt, Rect(), nullptr);

                if (!m_eval_templ_task.empty()) {
                    // mask/method 等 Matcher 配置取自该任务；须在 set_templ 之前调用，
                    // 否则 set_task_info 会把模板重置为任务自带的
                    analyzer.set_task_info(m_eval_templ_task);
                }
                if (!m_eval_roi.empty()) {
                    // set_task_info 会用任务自身的 roi 覆盖构造时的 roi，显式传入的 roi 在其后重设
                    analyzer.set_roi(m_eval_roi);
                }

                json::object result { { "template", templ_name } };
                std::filesystem::path templ_file = asst::utils::path(templ_name);
                if (templ_file.is_absolute() && std::filesystem::exists(templ_file)) {
                    cv::Mat templ = MAA_NS::imread(templ_file);
                    if (templ.empty()) {
                        result["hit"] = false;
                        result["error"] = "failed to load templ file";
                        LogError << __FUNCTION__ << "failed to load templ:" << templ_name;
                        all_ok = false;
                        results.emplace_back(std::move(result));
                        continue;
                    }
                    analyzer.set_templ(std::move(templ));
                }
                else {
                    analyzer.set_templ(templ_name);
                }
                analyzer.set_threshold(-1.0); // 放开阈值恒报最佳得分，hit 由 threshold 字段判定

                try {
                    auto result_opt = analyzer.analyze();
                    if (result_opt) {
                        result["score"] = result_opt->score;
                        result["rect"] = (json::value)(result_opt->rect);
                        result["hit"] = result_opt->score >= m_eval_threshold;
                    }
                    else {
                        // 阈值已放开仍无结果，只剩 roi 为空或模板大于 roi 等输入问题，不存在正常 miss
                        result["hit"] = false;
                        result["error"] = "no match result (check roi / template size)";
                        all_ok = false;
                    }
                }
                catch (const std::exception& e) {
                    // ASST_DEBUG 下模板不存在/加载失败会 throw，报错后继续评估其余模板
                    result["hit"] = false;
                    result["error"] = e.what();
                    all_ok = false;
                }
                LogInfo << __FUNCTION__ << image_path << templ_name << (result["hit"].as_boolean() ? "hit" : "miss")
                        << result.dumps();
                results.emplace_back(std::move(result));
            }

            callback(
                AsstMsg::SubTaskExtraInfo,
                json::object { { "what", "DebugImageTest" },
                               { "details",
                                 json::object { { "mode", "templ" },
                                                { "image", image_path },
                                                { "results", std::move(results) } } } });
        }
        catch (const std::exception& e) {
            all_ok = false;
            emit_eval_error("templ", image_path, e.what());
        }
    }
    return all_ok;
}

void asst::DebugTask::test_drops()
{
    size_t total = 0;
    size_t success = 0;
    for (const auto& entry : std::filesystem::directory_iterator("../../test/drops/screenshots/zh_cn")) {
        cv::Mat image = MAA_NS::imread(entry.path());
        if (image.empty()) {
            continue;
        }
        total += 1;
        cv::Mat resized;
        cv::resize(image, resized, cv::Size(1280, 720), 0, 0, cv::INTER_AREA);
        StageDropsImageAnalyzer analyzer(resized);
        success += analyzer.analyze();
    }
    Log.info(__FUNCTION__, success, "/", total);
}

void asst::DebugTask::test_skill_ready()
{
    int total = 0;
    int correct = 0;

    // 测试 y 类别（预期为 ready，即 true）
    for (const auto& entry : std::filesystem::directory_iterator(R"(../../test/skill_ready/y)")) {
        cv::Mat image = MAA_NS::imread(entry.path());
        BattlefieldClassifier analyzer(image);
        analyzer.set_object_of_interest({ .skill_ready = true });
        total++;
        auto result = analyzer.analyze()->skill_ready;
        // 记录日志：文件、预期结果、实际预测、得分、概率信息
        Log.info(
            __FUNCTION__,
            "File: ",
            entry.path().string(),
            " | Expected: Y (ready: true)",
            " | Predicted: ",
            result.ready,
            " | Score: ",
            result.score,
            " | Prob: ",
            result.prob);
        if (result.ready) {
            correct++;
        }
    }

    // 测试 n 类别（预期为 not ready，即 false）
    for (const auto& entry : std::filesystem::directory_iterator(R"(../../test/skill_ready/n)")) {
        cv::Mat image = MAA_NS::imread(entry.path());
        BattlefieldClassifier analyzer(image);
        analyzer.set_object_of_interest({ .skill_ready = true });
        total++;
        auto result = analyzer.analyze()->skill_ready;
        Log.info(
            __FUNCTION__,
            "File: ",
            entry.path().string(),
            " | Expected: N (ready: false)",
            " | Predicted: ",
            result.ready,
            " | Score: ",
            result.score,
            " | Prob: ",
            result.prob);
        if (!result.ready) {
            correct++;
        }
    }

    // 测试 c 类别（同样预期为 not ready）
    for (const auto& entry : std::filesystem::directory_iterator(R"(../../test/skill_ready/c)")) {
        cv::Mat image = MAA_NS::imread(entry.path());
        BattlefieldClassifier analyzer(image);
        analyzer.set_object_of_interest({ .skill_ready = true });
        total++;
        auto result = analyzer.analyze()->skill_ready;
        Log.info(
            __FUNCTION__,
            "File: ",
            entry.path().string(),
            " | Expected: C (ready: false)",
            " | Predicted: ",
            result.ready,
            " | Score: ",
            result.score,
            " | Prob: ",
            result.prob);
        if (!result.ready) {
            correct++;
        }
    }

    Log.info(__FUNCTION__, "Final Accuracy: ", correct, "/", total, " (", double(correct) / total, ")");
}

void asst::DebugTask::test_battle_image()
{
    cv::Mat image = MAA_NS::imread(utils::path("1.png"));
    cv::Mat resized;
    cv::resize(image, resized, cv::Size(1280, 720), 0, 0, cv::INTER_AREA);
    BattlefieldMatcher analyzer(resized);
    analyzer.set_object_of_interest({ .deployment = true });
    analyzer.analyze();
}

void asst::DebugTask::test_match_template()
{
    auto test_task = [](const std::string& path, const std::string& task_name) -> double {
        cv::Mat image = MAA_NS::imread(utils::path(path));
        cv::Mat resized;
        cv::resize(image, resized, cv::Size(1280, 720), 0, 0, cv::INTER_AREA);
        Matcher match_analyzer(resized, Rect(0, 0, 1280, 720));
        const auto& task_ptr = Task.get(task_name);
        const auto match_task_ptr = std::dynamic_pointer_cast<MatchTaskInfo>(task_ptr);
        match_analyzer.set_task_info(match_task_ptr);
        const auto& result_opt = match_analyzer.analyze();
        if (result_opt) {
            const auto& result = result_opt.value().to_string();
            Log.info("active", path, task_name, result);
            return result_opt.value().score;
        }
        else {
            Log.info("inactive", path, task_name);
            return 0.;
        }
    };

    // test_task(
    //     "../../x64/Release/debug/roguelike/2024-07-27_16-32-25-198_raw.png",
    //     "Sarkaz@Roguelike@StageWindAndRain");

    // for (int i = 1; i <= 15; ++i) {
    //     test_task("../../test/dist/" + std::to_string(i) + ".png", "Sarkaz@Roguelike@StageCombatOps");
    //     test_task("../../test/dist/" + std::to_string(i) + ".png", "Sarkaz@Roguelike@StageBoskyPassage");
    //     test_task("../../test/dist/" + std::to_string(i) + ".png", "Sarkaz@Roguelike@StageEmergencyTransportation");
    //     test_task("../../test/dist/" + std::to_string(i) + ".png", "Sarkaz@Roguelike@StageWindAndRain");
    // }

#define TEST(expr)                                       \
    if (!(expr)) {                                       \
        throw std::runtime_error("Test failed: " #expr); \
    }

#define ASSERT_ACTIVE(path, task_name) TEST(test_task(path, task_name) > DoubleDiff)
#define ASSERT_INACTIVE(path, task_name) TEST(test_task(path, task_name) < DoubleDiff)

    ASSERT_INACTIVE("../../test/dist/12.png", "Sarkaz@Roguelike@StageBoskyPassage");
    ASSERT_ACTIVE("../../test/dist/13.png", "Sarkaz@Roguelike@StageEmergencyTransportation");
    ASSERT_ACTIVE("../../test/dist/14.png", "Sarkaz@Roguelike@StageWindAndRain");
    ASSERT_ACTIVE("../../test/dist/15.png", "Sarkaz@Roguelike@StageEmergencyTransportation");
    ASSERT_ACTIVE("../../test/dist/#10160.png", "Sarkaz@Roguelike@StageTraderEnter");
    ASSERT_INACTIVE("../../test/dist/#10235.png", "Sarkaz@Roguelike@StageRefresh");

#undef TEST
#undef ASSERT_ACTIVE
#undef ASSERT_INACTIVE
}

bool asst::DebugTask::image_test_tile_projection()
{
    bool all_ok = true;
    for (const auto& stage : m_eval_stages) {
        const auto level = TilePack::find_level(stage);
        if (!level || level->key.stageId != stage) {
            LogError << __FUNCTION__ << "unknown or ambiguous stage ID:" << stage;
            callback(
                AsstMsg::SubTaskExtraInfo,
                json::object { { "what", "DebugImageTest" },
                               { "details",
                                 json::object { { "mode", "tile_projection" },
                                                { "stage_id", stage },
                                                { "error", "Unknown or ambiguous stage ID" } } } });
            all_ok = false;
            continue;
        }
        const auto projection = TilePack::calc(*level);
        std::optional<double> floor_z;
        for (int y = 0; y < level->get_height() && !floor_z; ++y) {
            for (int x = 0; x < level->get_width(); ++x) {
                if (level->get_item(y, x).heightType == static_cast<int>(TilePack::HeightType::Floor)) {
                    floor_z = Map::TileCalc2::get_tile_world_pos(*level, y, x)[2];
                    break;
                }
            }
        }
        json::array tiles;
        for (int y = 0; y < level->get_height(); ++y) {
            for (int x = 0; x < level->get_width(); ++x) {
                const Point loc(x, y);
                const auto normal = projection.normal_tile_info.find(loc);
                const auto selected = projection.side_tile_info.find(loc);
                if (normal == projection.normal_tile_info.end() || selected == projection.side_tile_info.end()) {
                    LogError << __FUNCTION__ << "missing projected tile:" << stage << loc;
                    all_ok = false;
                    continue;
                }
                const auto tile = level->get_item(y, x);
                json::object projected { { "tile", json::array { x, y } },
                                         { "normal", json::array { normal->second.pos.x, normal->second.pos.y } },
                                         { "selected", json::array { selected->second.pos.x, selected->second.pos.y } },
                                         { "tile_key", tile.tileKey },
                                         { "height_type", tile.heightType },
                                         { "buildable_type", tile.buildableType } };
                if (floor_z) {
                    // A diagnostic plane, never a statement that this tile was cleared or is buildable.
                    auto ground = Map::TileCalc2::get_tile_world_pos(*level, y, x);
                    ground[2] = *floor_z;
                    const auto floor_normal = Map::TileCalc2::world_to_screen(*level, ground, false);
                    const auto floor_selected = Map::TileCalc2::world_to_screen(*level, ground, true);
                    projected.emplace("floor_normal", json::array { floor_normal.x, floor_normal.y });
                    projected.emplace("floor_selected", json::array { floor_selected.x, floor_selected.y });
                }
                tiles.emplace_back(std::move(projected));
            }
        }
        callback(
            AsstMsg::SubTaskExtraInfo,
            json::object { { "what", "DebugImageTest" },
                           { "details",
                             json::object { { "mode", "tile_projection" },
                                            { "stage_id", level->key.stageId },
                                            { "level_id", level->key.levelId },
                                            { "name", level->key.name },
                                            { "width", level->get_width() },
                                            { "height", level->get_height() },
                                            { "camera_shift", json::array { 0, 0 } },
                                            { "live_camera_verified", false },
                                            { "floor_plane_available", floor_z.has_value() },
                                            { "floor_plane_live_verified", false },
                                            { "tiles", std::move(tiles) } } } });
    }
    return all_ok;
}
