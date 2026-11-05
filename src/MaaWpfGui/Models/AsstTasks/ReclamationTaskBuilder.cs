// <copyright file="ReclamationTaskBuilder.cs" company="MaaAssistantArknights">
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
using MaaWpfGui.Configuration.Single.MaaTask;
using MaaWpfGui.Configuration.Single.Settings;
using MaaWpfGui.Constants.Enums;

namespace MaaWpfGui.Models.AsstTasks;

/// <summary>
/// Translates queued Sand settings into the existing native task APIs.
/// </summary>
public static class ReclamationTaskBuilder
{
    /// <summary>
    /// Builds parameters without connecting a controller or starting a task.
    /// </summary>
    /// <param name="config">The persisted task settings.</param>
    /// <param name="client">The game client.</param>
    /// <param name="defaultTool">The localized native crafting target.</param>
    /// <returns>The native task parameters.</returns>
    public static AsstBaseTask Build(ReclamationTask config, ClientType client, string defaultTool)
    {
        if (config.Mode == ReclamationQueueMode.ResumeSand)
        {
            if (client != ClientType.EN)
            {
                throw new ArgumentException("Sand preparation requires the English game client.", nameof(client));
            }

            return new AsstCustomTask {
                CustomTasks = [
                    "SandFlow@WorldReady",
                    "SandFlow@ResumeOwnedFromHome",
                    "SandFlow@ResumeOwnedFromTerminal",
                    "SandFlow@ResumeOwnedFromThemes-After0",
                    "SandFlow@ResumeOwnedFromThemes",
                    "SandFlow@ResumeOwnedFromHome-After1",
                    "SandFlow@ResumeOwnedFromHome-After4",
                ],
            };
        }

        if (config.Mode != ReclamationQueueMode.ProsperityInSave)
        {
            throw new ArgumentOutOfRangeException(nameof(config));
        }

        var tool = string.IsNullOrWhiteSpace(config.ToolToCraft)
            ? defaultTool
            : config.ToolToCraft.Trim();
        if (string.IsNullOrWhiteSpace(tool))
        {
            throw new ArgumentException("A crafting tool name is required.", nameof(defaultTool));
        }

        return new AsstReclamationTask {
            Theme = ReclamationTheme.Tales,
            Mode = (int)ReclamationMode.ProsperityInSave,
            ToolToCraft = [tool],
            MaxCraftCountPerRound = Math.Clamp(config.MaxCraftCountPerRound, 1, 99),
            ClearStore = config.ClearStore,
        };
    }
}
