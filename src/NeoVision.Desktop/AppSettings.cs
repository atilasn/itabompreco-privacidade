namespace NeoVision.Desktop;

public sealed class AppSettings
{
    public string DatabaseConnectionString { get; init; } = "";
    public string AiBaseUrl { get; init; } = "http://127.0.0.1:9080";
    public string WebSocketEventsUrl { get; init; } = "ws://127.0.0.1:9080/ws/events";
    public string RecordingsPath { get; init; } = "";
}
