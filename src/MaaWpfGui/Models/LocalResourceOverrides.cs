// <copyright file="LocalResourceOverrides.cs" company="MaaAssistantArknights">
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
using System.Collections.Concurrent;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace MaaWpfGui.Models;

public static class LocalResourceOverrides
{
    private static readonly ConcurrentDictionary<string, Lazy<JObject>> _manifests = new();

    public static void CopyFile(string source, string destination, string resourceRoot, string manifestPath)
    {
        string relative = Path.GetRelativePath(resourceRoot, destination).Replace('\\', '/');
        if (relative.StartsWith("../", StringComparison.Ordinal) || Path.IsPathRooted(relative))
        {
            throw new InvalidDataException("Resource update destination is outside the resource directory");
        }

        if (!File.Exists(manifestPath))
        {
            File.Copy(source, destination, true);
            return;
        }

        JObject manifest = _manifests.GetOrAdd(manifestPath, path => new Lazy<JObject>(() => {
            var data = JObject.Parse(File.ReadAllText(path));
            if ((int?)data["schema_version"] != 1 || data["files"] is not JObject)
            {
                throw new InvalidDataException("Invalid local resource override manifest");
            }

            return data;
        })).Value;
        JToken? plan = manifest["files"]?[relative];
        if (plan == null)
        {
            File.Copy(source, destination, true);
            return;
        }

        if ((bool?)plan["delete_file"] == true)
        {
            File.Delete(destination);
            return;
        }

        byte[] contents;
        if (plan["json"] is JObject patch)
        {
            var merged = Apply(JToken.Parse(File.ReadAllText(source)), patch);
            contents = System.Text.Encoding.UTF8.GetBytes(merged.ToString(Formatting.Indented) + "\n");
        }
        else if (plan["content_base64"]?.Value<string>() is string encoded)
        {
            contents = Convert.FromBase64String(encoded);
        }
        else
        {
            throw new InvalidDataException("Invalid local resource file override");
        }

        string temporary = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllBytes(temporary, contents);
            File.Move(temporary, destination, true);
        }
        finally
        {
            File.Delete(temporary);
        }
    }

    private static JToken Apply(JToken remote, JObject patch)
    {
        if (patch.TryGetValue("replace", out JToken? replacement))
        {
            return replacement.DeepClone();
        }

        if (patch["properties"] is not JObject properties || patch["remove"] is not JArray removed)
        {
            throw new InvalidDataException("Invalid local JSON override");
        }

        JObject result = remote as JObject ?? new JObject();
        foreach (JToken name in removed)
        {
            result.Remove(name.Value<string>() ?? throw new InvalidDataException("Missing removed property"));
        }

        foreach (JProperty property in properties.Properties())
        {
            result[property.Name] = Apply(result[property.Name] ?? JValue.CreateNull(),
                property.Value as JObject ?? throw new InvalidDataException("Invalid property override"));
        }

        return result;
    }
}
