using System.Net.Http;
using System.Text.Json;

namespace NeoVision.Desktop.Services;

public sealed class AiApiClient : IDisposable
{
    private readonly HttpClient _http;

    public AiApiClient(string baseUrl, TimeSpan? timeout = null)
    {
        var root = baseUrl.TrimEnd('/');
        _http = new HttpClient
        {
            BaseAddress = new Uri(root + "/"),
            Timeout = timeout ?? TimeSpan.FromSeconds(8),
        };
    }

    public async Task<(bool Ok, string Message)> TryHealthAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.GetAsync("health", cancellationToken).ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return (false, $"HTTP {(int)response.StatusCode}: {body}");

            using var doc = JsonDocument.Parse(body);
            var status = doc.RootElement.TryGetProperty("status", out var s) ? s.GetString() : null;
            return status == "ok"
                ? (true, "Serviço online (status ok).")
                : (false, $"Resposta inesperada: {body}");
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    public void Dispose() => _http.Dispose();
}
