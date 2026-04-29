using System.Windows;
using Microsoft.Extensions.Configuration;

namespace NeoVision.Desktop;

public partial class App : Application
{
    public static AppSettings Settings { get; private set; } = null!;

    protected override void OnStartup(StartupEventArgs e)
    {
        var config = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.json", optional: true, reloadOnChange: true)
            .Build();

        Settings = new AppSettings
        {
            DatabaseConnectionString = config["Database:ConnectionString"] ?? "",
            AiBaseUrl = config["Services:AiBaseUrl"] ?? "http://127.0.0.1:9080",
            WebSocketEventsUrl = config["Services:WebSocketEventsUrl"] ?? "ws://127.0.0.1:9080/ws/events",
            RecordingsPath = config["Storage:RecordingsPath"] ?? "",
        };

        StoragePaths.EnsureRecordingsDirectoryExists(App.Settings.RecordingsPath);

        base.OnStartup(e);
    }
}
