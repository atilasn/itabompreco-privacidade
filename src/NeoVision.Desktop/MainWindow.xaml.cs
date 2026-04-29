using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using NeoVision.Desktop.Services;
using System.Threading;

namespace NeoVision.Desktop;

public partial class MainWindow : Window
{
    private static readonly HashSet<string> EmBreveTags = new(
        new[]
        {
            "sistema_rel", "sistema_users", "ia_anal", "ia_alerta", "ia_previs", "ia_chat",
            "auto_rot", "auto_ac", "auto_luz", "auto_sens", "cam_live", "cam_snap", "cam_mov",
            "tr_mon", "tr_ev", "tr_log", "tr_not",
        },
        StringComparer.Ordinal);

    private IReadOnlyList<DiscoveredOnvifDevice> _ultimaDescobertaOnvif =
        Array.Empty<DiscoveredOnvifDevice>();

    private IReadOnlyList<RecordingListItem> _recordingsAll = Array.Empty<RecordingListItem>();

    public MainWindow()
    {
        InitializeComponent();
        AiBaseUrlBox.Text = App.Settings.AiBaseUrl;
        RecordingsPathText.Text = StoragePaths.ResolveRecordingsDirectory(App.Settings.RecordingsPath);
        ReloadRecordingsDataCore();
    }

    private void RootScrollViewer_Loaded(object sender, RoutedEventArgs e)
    {
        var p = Path.Combine(AppContext.BaseDirectory, "Assets", "painel-referencia.png");
        if (File.Exists(p))
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.UriSource = new Uri(p, UriKind.Absolute);
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.EndInit();
            ReferenceImage.Source = bmp;
        }
        else
        {
            ReferenceImage.Visibility = Visibility.Collapsed;
        }

        var dashSis = Path.Combine(AppContext.BaseDirectory, "Assets", "dash-sistema.png");
        if (File.Exists(dashSis))
        {
            var ico = new BitmapImage();
            ico.BeginInit();
            ico.UriSource = new Uri(dashSis, UriKind.Absolute);
            ico.CacheOption = BitmapCacheOption.OnLoad;
            ico.EndInit();
            DashSistemaImage.Source = ico;
        }
        else
        {
            DashSistemaImage.Visibility = Visibility.Collapsed;
        }
    }

    private void DashboardButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string t)
            return;
        if (EmBreveTags.Contains(t))
        {
            MessageBox.Show(
                "Funcionalidade em desenvolvimento.",
                "NeoVision AI",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        switch (t)
        {
            case "sistema_dash":
                RootScrollViewer.ScrollToVerticalOffset(0);
                return;
            case "sistema_config":
                MessageBox.Show(
                    "O ficheiro appsettings.json fica na pasta do NeoVision.exe (junto do instalador / publicação). Aí ajusta a ligação MySQL, URL da API e, se quiser, Storage:RecordingsPath.",
                    "Configurações",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            case "sistema_srv":
                CardApi.BringIntoView();
                return;
            case "ia_face":
                MessageBox.Show(
                    "A API de IA expõe POST /ai/recognize. A ligação completa a partir desta app será o próximo passo.",
                    "Reconhecimento facial",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            case "auto_port":
                MessageBox.Show(
                    "A API tem POST /automation/gate/open (demonstração). Botão de portão a integrar aqui.",
                    "Portões",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            case "cam_grav":
                CardGravacoes.BringIntoView();
                return;
            case "cam_ip":
                CardCameras.BringIntoView();
                return;
            case "tr_status":
                CardApi.BringIntoView();
                return;
        }
    }

    private string GetAiBaseUrl() =>
        string.IsNullOrWhiteSpace(AiBaseUrlBox.Text) ? App.Settings.AiBaseUrl : AiBaseUrlBox.Text.Trim();

    private Brush B(string key) =>
        TryFindResource(key) as Brush ?? SystemColors.ControlTextBrush;

    private async void TestAiButton_Click(object sender, RoutedEventArgs e)
    {
        TestAiButton.IsEnabled = false;
        AiStatusText.Foreground = B("Brush.StatusNeutral");
        AiStatusText.Text = "A testar ligação…";

        try
        {
            using var client = new AiApiClient(GetAiBaseUrl());
            var (ok, message) = await client.TryHealthAsync().ConfigureAwait(true);
            AiStatusText.Foreground = ok ? B("Brush.StatusOk") : B("Brush.StatusBad");
            AiStatusText.Text = message;
        }
        finally
        {
            TestAiButton.IsEnabled = true;
        }
    }

    private async void TestDbButton_Click(object sender, RoutedEventArgs e)
    {
        TestDbButton.IsEnabled = false;
        DbStatusText.Foreground = B("Brush.StatusNeutral");
        DbStatusText.Text = "A testar base de dados…";

        try
        {
            var (ok, message) = await MySqlProbe.TryConnectAsync(
                App.Settings.DatabaseConnectionString).ConfigureAwait(true);
            DbStatusText.Foreground = ok ? B("Brush.StatusOk") : B("Brush.StatusBad");
            DbStatusText.Text = message;
        }
        finally
        {
            TestDbButton.IsEnabled = true;
        }
    }

    private async void ScanOnvifButton_Click(object sender, RoutedEventArgs e)
    {
        ScanOnvifButton.IsEnabled = false;
        OnvifList.Items.Clear();
        OnvifStatusText.Foreground = B("Brush.StatusNeutral");
        OnvifStatusText.Text = "A procurar dispositivos na rede local (até 4 s)…";

        try
        {
            var list = await OnvifWsDiscovery.ProbeAsync(
                listenDuration: TimeSpan.FromSeconds(4),
                cancellationToken: CancellationToken.None).ConfigureAwait(true);

            _ultimaDescobertaOnvif = list;

            foreach (var d in list)
            {
                var addrs = string.Join("  ", d.XAddrs);
                var from = d.Remote is not null ? d.Remote.ToString() : "?";
                var line = $"{from}  |  {addrs}";
                if (!string.IsNullOrWhiteSpace(d.Scopes))
                {
                    var s = d.Scopes.Split();
                    if (s.Length > 0)
                    {
                        var label = s[0].Length > 60 ? s[0][..60] + "…" : s[0];
                        line += "  |  " + label;
                    }
                }

                OnvifList.Items.Add(line);
            }

            OnvifStatusText.Foreground = B("Brush.StatusOk");
            OnvifStatusText.Text = list.Count == 0
                ? "Nenhum dispositivo respondeu. Confirme: mesma Wi-Fi, firewall UDP, câmera com ONVIF ativo."
                : $"Encontrado(s) {list.Count} dispositivo(s).";
        }
        catch (Exception ex)
        {
            OnvifStatusText.Foreground = B("Brush.StatusBad");
            OnvifStatusText.Text = "Erro: " + ex.Message;
        }
        finally
        {
            ScanOnvifButton.IsEnabled = true;
        }
    }

    private async void SaveOnvifToDbButton_Click(object sender, RoutedEventArgs e)
    {
        SaveOnvifToDbButton.IsEnabled = false;
        OnvifStatusText.Foreground = B("Brush.StatusNeutral");
        OnvifStatusText.Text = "A guardar na base…";

        try
        {
            var (ins, _, msg) = await CameraRepository.TrySaveDiscoveredAsync(
                _ultimaDescobertaOnvif,
                App.Settings.DatabaseConnectionString,
                CancellationToken.None).ConfigureAwait(true);
            OnvifStatusText.Foreground = ins > 0 ? B("Brush.StatusOk") : B("Brush.StatusNeutral");
            if (msg.Contains("Defina", StringComparison.Ordinal) || msg.Contains("Nada", StringComparison.Ordinal))
                OnvifStatusText.Foreground = B("Brush.StatusBad");
            OnvifStatusText.Text = msg;
        }
        catch (Exception ex)
        {
            OnvifStatusText.Foreground = B("Brush.StatusBad");
            OnvifStatusText.Text = "Erro MySQL: " + ex.Message;
        }
        finally
        {
            SaveOnvifToDbButton.IsEnabled = true;
        }
    }

    private async void RefreshCamerasButton_Click(object sender, RoutedEventArgs e)
    {
        RefreshCamerasButton.IsEnabled = false;
        CamerasStatusText.Foreground = B("Brush.StatusNeutral");
        CamerasStatusText.Text = "A carregar câmeras…";

        try
        {
            var (ok, rows, message) = await CameraRepository.TryListAsync(
                App.Settings.DatabaseConnectionString,
                CancellationToken.None).ConfigureAwait(true);

            if (!ok)
            {
                CamerasStatusText.Foreground = B("Brush.StatusBad");
                CamerasStatusText.Text = message;
                CamerasItems.ItemsSource = null;
                return;
            }

            CamerasItems.ItemsSource = rows.Select(CameraGridItem.FromRow).ToList();
            CamerasStatusText.Foreground = rows.Count == 0
                ? B("Brush.StatusNeutral")
                : B("Brush.StatusOk");
            CamerasStatusText.Text = message;
        }
        catch (Exception ex)
        {
            CamerasStatusText.Foreground = B("Brush.StatusBad");
            CamerasStatusText.Text = "Erro: " + ex.Message;
        }
        finally
        {
            RefreshCamerasButton.IsEnabled = true;
        }
    }

    private void OpenRecordingsFolderButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            OpenRecordingsFolderButton.IsEnabled = false;
            var path = StoragePaths.ResolveRecordingsDirectory(App.Settings.RecordingsPath);
            StoragePaths.OpenInWindowsExplorer(path);
            ReloadRecordingsDataCore();
        }
        finally
        {
            OpenRecordingsFolderButton.IsEnabled = true;
        }
    }

    private void ReloadRecordingsDataCore()
    {
        StoragePaths.EnsureRecordingsDirectoryExists(App.Settings.RecordingsPath);
        RecordingsPathText.Text = StoragePaths.ResolveRecordingsDirectory(App.Settings.RecordingsPath);
        _recordingsAll = RecordingsIndex.LoadAll(App.Settings.RecordingsPath);
        ApplyRecordingsFilter();
    }

    private void RefreshRecordingsListFromDisk()
    {
        try
        {
            RefreshRecordingsListButton.IsEnabled = false;
            ReloadRecordingsDataCore();
        }
        finally
        {
            RefreshRecordingsListButton.IsEnabled = true;
        }
    }

    private void ApplyRecordingsFilter()
    {
        IEnumerable<RecordingListItem> q = _recordingsAll;
        if (RecordingsFilterFrom.SelectedDate is { } d0)
        {
            var from = d0.Date;
            q = q.Where(x => x.LastWriteLocal.Date >= from);
        }
        if (RecordingsFilterTo.SelectedDate is { } d1)
        {
            var to = d1.Date;
            q = q.Where(x => x.LastWriteLocal.Date <= to);
        }
        var name = RecordingsFilterName.Text?.Trim();
        if (!string.IsNullOrEmpty(name))
            q = q.Where(x => x.FileName.Contains(name, StringComparison.OrdinalIgnoreCase));
        var list = q.ToList();
        RecordingsListView.ItemsSource = list;
        if (list.Count == 0)
        {
            RecordingsCountText.Foreground = B("Brush.StatusNeutral");
            RecordingsCountText.Text = _recordingsAll.Count == 0
                ? "Nenhum ficheiro na pasta. As gravações serão listadas aqui (data, nome, tamanho)."
                : "Nenhum ficheiro com o filtro atual — limpe os filtros ou alargue o intervalo de datas.";
        }
        else
        {
            RecordingsCountText.Foreground = B("Brush.StatusOk");
            RecordingsCountText.Text = list.Count + " ficheiro(s) (de " + _recordingsAll.Count + " no total).";
        }
    }

    private void RefreshRecordingsListButton_Click(object sender, RoutedEventArgs e) => RefreshRecordingsListFromDisk();

    private void RecordingsFilterApplyButton_Click(object sender, RoutedEventArgs e) => ApplyRecordingsFilter();

    private void RecordingsFilterClearButton_Click(object sender, RoutedEventArgs e)
    {
        RecordingsFilterFrom.SelectedDate = null;
        RecordingsFilterTo.SelectedDate = null;
        RecordingsFilterName.Text = "";
        ApplyRecordingsFilter();
    }

    private void OpenRecordingFileButton_Click(object sender, RoutedEventArgs e) => OpenSelectedRecordingFile();

    private void RecordingsListView_MouseDoubleClick(object sender, RoutedEventArgs e) => OpenSelectedRecordingFile();

    private void OpenSelectedRecordingFile()
    {
        if (RecordingsListView.SelectedItem is not RecordingListItem r)
        {
            MessageBox.Show("Selecione um ficheiro na lista (clique numa linha).", "Gravações", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        try
        {
            _ = Process.Start(
                new ProcessStartInfo
                {
                    FileName = r.FullPath,
                    UseShellExecute = true,
                });
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "Não foi possível abrir o ficheiro", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }
}
