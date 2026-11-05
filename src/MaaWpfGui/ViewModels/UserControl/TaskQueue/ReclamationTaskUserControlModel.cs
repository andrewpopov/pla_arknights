// <copyright file="ReclamationTaskUserControlModel.cs" company="MaaAssistantArknights">
// Part of the MaaWpfGui project, maintained by the MaaAssistantArknights team (Maa Team)
// Copyright (C) 2021-2026 MaaAssistantArknights Contributors
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License v3.0 only as published by
// the Free Software Foundation, either version 3 of the License, or
// any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY
// </copyright>
#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using MaaWpfGui.Configuration.Single.MaaTask;
using MaaWpfGui.Constants.Enums;
using MaaWpfGui.Helper;
using MaaWpfGui.Models;
using MaaWpfGui.Models.AsstTasks;
using MaaWpfGui.Utilities;
using MaaWpfGui.Utilities.ValueType;
using MaaWpfGui.ViewModels.UI;
using static MaaWpfGui.Main.AsstProxy;

namespace MaaWpfGui.ViewModels.UserControl.TaskQueue;

public class ReclamationTaskUserControlModel : TaskSettingsViewModel, ReclamationTaskUserControlModel.ISerialize
{
    public static ReclamationTaskUserControlModel Instance { get; } = new();

    private ReclamationTaskUserControlModel()
    {
        LocalizationHelper.LanguageChanged += () => {
            Modes.RefreshLocalization();
            NotifyOfPropertyChange(nameof(Description));
        };
    }

    public LocalizedObservableList<ReclamationQueueMode> Modes { get; } = new(
        (ReclamationQueueMode.ResumeSand, "TaskQueue.Reclamation.ResumeSand"),
        (ReclamationQueueMode.ProsperityInSave, "Toolbox.MiniGame.Reclamation.Mode.ProsperityInSave"));

    public ReclamationQueueMode Mode
    {
        get => GetTaskConfig<ReclamationTask>().Mode;
        set => SetTaskConfig<ReclamationTask>(t => t.Mode == value, t => t.Mode = value);
    }

    [PropertyDependsOn(nameof(Mode))]
    public bool ShowCraftSettings => Mode == ReclamationQueueMode.ProsperityInSave;

    [PropertyDependsOn(nameof(Mode))]
    public string Description => LocalizationHelper.GetString(ShowCraftSettings
        ? "TaskQueue.Reclamation.Prosperity.Tip" : "TaskQueue.Reclamation.ResumeSand.Tip");

    public string ToolToCraft
    {
        get => GetTaskConfig<ReclamationTask>().ToolToCraft;
        set => SetTaskConfig<ReclamationTask>(t => t.ToolToCraft == value, t => t.ToolToCraft = value);
    }

    public int MaxCraftCountPerRound
    {
        get => GetTaskConfig<ReclamationTask>().MaxCraftCountPerRound;
        set => SetTaskConfig<ReclamationTask>(t => t.MaxCraftCountPerRound == value, t => t.MaxCraftCountPerRound = Math.Clamp(value, 1, 99));
    }

    public bool ClearStore
    {
        get => GetTaskConfig<ReclamationTask>().ClearStore;
        set => SetTaskConfig<ReclamationTask>(t => t.ClearStore == value, t => t.ClearStore = value);
    }

    public override void RefreshUI(BaseTask baseTask)
    {
        if (baseTask is ReclamationTask)
        {
            Refresh();
        }
    }

    public override (bool? IsSuccess, IEnumerable<int> TaskId) SerializeTask(BaseTask? baseTask, int? taskId = null) => (this as ISerialize).Serialize(baseTask, taskId);

    private interface ISerialize : ITaskQueueModelSerialize
    {
        (bool? IsSuccess, IEnumerable<int> TaskId) ITaskQueueModelSerialize.Serialize(BaseTask? baseTask, int? taskId)
        {
            if (baseTask is not ReclamationTask config)
            {
                return (null, []);
            }

            if (config.Mode == ReclamationQueueMode.ResumeSand &&
                !File.Exists(Path.Combine(PathsHelper.BaseDir, "modules", "sand", "pack", "resource", "tasks", "SandFlow.json")))
            {
                throw new InvalidOperationException(LocalizationHelper.GetString("TaskQueue.Reclamation.ModuleMissing"));
            }

            var client = SettingsViewModel.GameSettings.ClientType;
            if (config.Mode == ReclamationQueueMode.ResumeSand && client != ClientType.EN)
            {
                throw new InvalidOperationException(LocalizationHelper.GetString("TaskQueue.Reclamation.EnglishOnly"));
            }

            var defaultTool = config.Mode == ReclamationQueueMode.ProsperityInSave
                ? LocalizationHelper.GetString("Toolbox.MiniGame.Reclamation.ToolToCraft.Placeholder", DataHelper.ClientLanguageMapper[client])
                : string.Empty;
            var task = ReclamationTaskBuilder.Build(config, client, defaultTool);
            return taskId switch {
                int id when id > 0 => (Instances.AsstProxy.AsstSetTaskParamsEncoded(id, task), [id]),
                null => FromSingle(Instances.AsstProxy.AsstAppendTaskWithEncoding(TaskType.Reclamation, task)),
                _ => (null, []),
            };
        }
    }
}
