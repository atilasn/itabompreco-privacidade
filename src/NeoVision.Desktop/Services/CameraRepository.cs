using System.Collections.ObjectModel;
using MySqlConnector;

namespace NeoVision.Desktop.Services;

public sealed record CameraRow(
    Guid Id,
    string Name,
    string IpAddress,
    int? HttpPort,
    string? RtspUrl,
    string? OnvifEndpoint,
    bool IsEnabled);

public static class CameraRepository
{
    public static (string? OnvifUrl, string? Ip, int? HttpPort) PickEndpoint(DiscoveredOnvifDevice d)
    {
        foreach (var raw in d.XAddrs)
        {
            if (string.IsNullOrWhiteSpace(raw))
                continue;
            if (!raw.StartsWith("http", StringComparison.OrdinalIgnoreCase))
                continue;
            if (!Uri.TryCreate(raw.Trim(), UriKind.Absolute, out var u))
                continue;
            var host = string.IsNullOrEmpty(u.IdnHost) ? u.Host : u.IdnHost;
            if (string.IsNullOrEmpty(host))
                continue;
            return (Truncate(raw.Trim(), 512), host, u.Port);
        }

        return (null, null, null);
    }

    public static async Task<(int Inserted, int Skipped, string Message)> TrySaveDiscoveredAsync(
        IReadOnlyList<DiscoveredOnvifDevice> devices,
        string connectionString,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(connectionString))
            return (0, 0, "Defina a connection string em appsettings.json.");

        if (devices.Count == 0)
            return (0, 0, "Nada para guardar. Faça “Procurar câmeras ONVIF” antes.");

        await using var conn = new MySqlConnection(connectionString);
        await conn.OpenAsync(cancellationToken).ConfigureAwait(false);

        var inserted = 0;
        var skipped = 0;

        foreach (var d in devices)
        {
            var t = PickEndpoint(d);
            if (t.OnvifUrl is null || string.IsNullOrEmpty(t.Ip) || t.HttpPort is null)
            {
                skipped++;
                continue;
            }

            var (onvifUrl, ip, port) = (t.OnvifUrl, t.Ip, t.HttpPort.Value);

            await using (var check = new MySqlCommand(
                "SELECT 1 FROM cameras WHERE onvif_endpoint = @e LIMIT 1",
                conn))
            {
                check.Parameters.AddWithValue("@e", onvifUrl);
                var exists = await check.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false) != null;
                if (exists)
                {
                    skipped++;
                    continue;
                }
            }

            var name = Truncate("Câmara " + ip, 128);
            var id = Guid.NewGuid().ToByteArray();
            const string sql = """
                INSERT INTO cameras (id, name, ip_address, http_port, onvif_endpoint, is_enabled, last_seen_at, created_at)
                VALUES (@id, @name, @ip, @port, @onv, 1, UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))
                """;

            await using (var ins = new MySqlCommand(sql, conn))
            {
                ins.Parameters.Add(new MySqlParameter("id", MySqlDbType.Binary, 16) { Value = id });
                ins.Parameters.AddWithValue("@name", name);
                ins.Parameters.AddWithValue("@ip", Truncate(ip, 45));
                ins.Parameters.AddWithValue("@port", (uint)port);
                ins.Parameters.AddWithValue("@onv", onvifUrl);
                await ins.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            inserted++;
        }

        return (inserted, skipped, $"MySQL: inserida(s) {inserted} linha(s); ignorada(s) {skipped} (duplicado ou sem URL http).");
    }

    public static async Task<(bool Ok, IReadOnlyList<CameraRow> Rows, string Message)> TryListAsync(
        string connectionString,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(connectionString))
            return (false, Array.Empty<CameraRow>(), "Defina a connection string em appsettings.json.");

        const string sql = """
            SELECT id, name, ip_address, http_port, rtsp_url, onvif_endpoint, is_enabled
            FROM cameras
            ORDER BY name
            """;

        await using var conn = new MySqlConnection(connectionString);
        await conn.OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var cmd = new MySqlCommand(sql, conn);
        await using var r = await cmd.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);

        var list = new List<CameraRow>();

        while (await r.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            var idBytes = (byte[])r["id"];
            var g = new Guid(idBytes);
            var name = r["name"] as string ?? "";
            var ip = r["ip_address"] as string ?? "";
            int? port = r["http_port"] is DBNull ? null : Convert.ToInt32(r["http_port"]);
            var rtsp = r["rtsp_url"] is DBNull ? null : (string)r["rtsp_url"];

            var onv = r["onvif_endpoint"] is DBNull ? null : (string)r["onvif_endpoint"];
            var en = r["is_enabled"] is not DBNull && Convert.ToBoolean(r["is_enabled"]);

            list.Add(new CameraRow(g, name, ip, port, string.IsNullOrWhiteSpace(rtsp) ? null : rtsp, string.IsNullOrWhiteSpace(onv) ? null : onv, en));
        }

        return (true, new ReadOnlyCollection<CameraRow>(list), list.Count == 0 ? "Nenhuma câmara em cameras." : $"{list.Count} câmara(s).");
    }

    private static string Truncate(string s, int max) =>
        s.Length <= max ? s : s[..max];
}
