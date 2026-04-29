using System.IO;

namespace NeoVision.Desktop;

public sealed class RecordingListItem
{
    public required string FileName { get; init; }
    public required string RelativePath { get; init; }
    public required string FullPath { get; init; }
    public DateTime LastWriteLocal { get; init; }
    public long SizeBytes { get; init; }

    public string DateDisplay => LastWriteLocal.ToString("yyyy-MM-dd  HH:mm:ss");

    public string SizeDisplay => FormatSize(SizeBytes);

    public static string FormatSize(long b)
    {
        if (b < 1024L)
            return b + " B";
        var kb = b / 1024.0;
        if (kb < 1024.0)
            return kb.ToString("0.##") + " KB";
        var mb = kb / 1024.0;
        if (mb < 1024.0)
            return mb.ToString("0.##") + " MB";
        return (mb / 1024.0).ToString("0.##") + " GB";
    }
}

public static class RecordingsIndex
{
    public static IReadOnlyList<RecordingListItem> LoadAll(string? configuredPath)
    {
        var root = StoragePaths.ResolveRecordingsDirectory(configuredPath);
        if (!Directory.Exists(root))
            return Array.Empty<RecordingListItem>();

        var rootFull = Path.GetFullPath(root);
        var list = new List<RecordingListItem>();

        foreach (var f in Directory.EnumerateFiles(rootFull, "*", SearchOption.AllDirectories))
        {
            if ((File.GetAttributes(f) & FileAttributes.Hidden) == FileAttributes.Hidden)
                continue;
            var fi = new FileInfo(f);
            var rel = Path.GetRelativePath(rootFull, f);
            if (string.IsNullOrEmpty(rel))
                rel = fi.Name;
            var fn = rel.Contains('\\', StringComparison.Ordinal) || rel.Contains('/', StringComparison.Ordinal)
                ? rel
                : fi.Name;
            list.Add(
                new RecordingListItem
                {
                    FileName = fn,
                    RelativePath = rel,
                    FullPath = f,
                    LastWriteLocal = fi.LastWriteTime,
                    SizeBytes = fi.Length,
                });
        }

        return list
            .OrderByDescending(x => x.LastWriteLocal)
            .ToList();
    }
}
