using MySqlConnector;

namespace NeoVision.Desktop.Services;

public static class MySqlProbe
{
    public static async Task<(bool Ok, string Message)> TryConnectAsync(
        string connectionString,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(connectionString))
            return (false, "Connection string vazia. Defina em appsettings.json, secção Database.");

        try
        {
            await using var conn = new MySqlConnection(connectionString);
            await conn.OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var cmd = new MySqlCommand("SELECT 1", conn);
            var one = await cmd.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false);
            return (true, one?.ToString() == "1"
                ? "MySQL: ligação OK (SELECT 1)."
                : "MySQL: ligado, resposta inesperada.");
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }
}
