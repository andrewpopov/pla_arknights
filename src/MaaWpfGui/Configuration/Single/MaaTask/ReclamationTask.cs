// <copyright file="ReclamationTask.cs" company="MaaAssistantArknights">
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
using static MaaWpfGui.Main.AsstProxy;

namespace MaaWpfGui.Configuration.Single.MaaTask;

/// <summary>
/// Queued Sand preparation or native prosperity farming in an existing save.
/// </summary>
public class ReclamationTask : BaseTask
{
    public ReclamationTask()
    {
        TaskType = TaskType.Reclamation;
        IsEnable = false;
    }

    /// <summary>
    /// Gets or sets the queue schema, distinguishing this task from legacy Toolbox entries.
    /// </summary>
    public int QueueVersion { get; set; } = 2;

    public ReclamationQueueMode Mode { get; set; } = ReclamationQueueMode.ResumeSand;

    public string ToolToCraft { get; set; } = string.Empty;

    public int MaxCraftCountPerRound { get; set; } = 1;

    public bool ClearStore { get; set; }
}

/// <summary>
/// Sand queue operations; neither operation creates or resets a save.
/// </summary>
public enum ReclamationQueueMode
{
    ResumeSand,
    ProsperityInSave,
}
