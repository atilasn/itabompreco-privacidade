using System.Diagnostics;
using System.IO;

namespace NeoVision.Desktop;

public static class StoragePaths
{
    public static string ResolveRecordingsDirectory(string? configuredPath)
    {
        if (!string.IsNullOrWhiteSpace(configuredPath))
            return Path.GetFullPath(configuredPath.Trim());
        return Path.Join(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "NeoVision",
            "recordings");
    }

    public static void EnsureRecordingsDirectoryExists(string? configuredPath)
    {
        var path = ResolveRecordingsDirectory(configuredPath);
        Directory.CreateDirectory(path);
    }

    public static void OpenInWindowsExplorer(string directoryPath)
    {
        directoryPath = Path.GetFullPath(directoryPath);
        Directory.CreateDirectory(directoryPath);
        _ = Process.Start(
            new ProcessStartInfo
            {
                FileName = directoryPath,
                UseShellExecute = true,
            });
    }
}
