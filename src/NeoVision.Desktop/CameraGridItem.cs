using NeoVision.Desktop.Services;

namespace NeoVision.Desktop;

public sealed class CameraGridItem
{
    public CameraGridItem(string name, string details)
    {
        Name = name;
        Details = details;
    }

    public string Name { get; }
    public string Details { get; }

    public static CameraGridItem FromRow(CameraRow row)
    {
        var host = row.IpAddress;
        if (row.HttpPort is { } p)
            host += ":" + p;

        var bits = new List<string>(4) { host };
        bits.Add(string.IsNullOrEmpty(row.RtspUrl) ? "RTSP não definido" : "RTSP definido");
        bits.Add(row.OnvifEndpoint is not null ? "ONVIF" : "sem ONVIF");
        bits.Add(row.IsEnabled ? "Ativa" : "Inativa");

        return new CameraGridItem(row.Name, string.Join(" · ", bits));
    }
}
