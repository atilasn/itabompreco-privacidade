using System.Collections.ObjectModel;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Xml.Linq;

namespace NeoVision.Desktop.Services;

public sealed class DiscoveredOnvifDevice
{
    public IPEndPoint? Remote { get; init; }
    public string[] XAddrs { get; init; } = Array.Empty<string>();
    public string? Scopes { get; init; }
}

public static class OnvifWsDiscovery
{
    private static readonly IPEndPoint Multicast = new(IPAddress.Parse("239.255.255.250"), 3702);

    /// <summary>
    /// Procura dispositivos ONVIF (WS-Discovery, UDP, ~4s). Rede local; firewall UDP 3702.
    /// </summary>
    public static Task<ReadOnlyCollection<DiscoveredOnvifDevice>> ProbeAsync(
        TimeSpan? listenDuration = null,
        CancellationToken cancellationToken = default)
    {
        // Bloquear thread da UI: executar noutro contexto; o serviço em si é I/O.
        return Task.Run(
            () => ProbeSync(listenDuration ?? TimeSpan.FromSeconds(4), cancellationToken),
            cancellationToken);
    }

    private static ReadOnlyCollection<DiscoveredOnvifDevice> ProbeSync(
        TimeSpan listenDuration,
        CancellationToken cancellationToken)
    {
        var found = new List<DiscoveredOnvifDevice>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var deadline = DateTime.UtcNow + listenDuration;

        using var udp = new UdpClient(0);
        udp.Client.ReceiveTimeout = 400;
        udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);

        var p1 = BuildProbe(true);
        var p2 = BuildProbe(false);
        udp.Send(Encoding.UTF8.GetBytes(p1), p1.Length, Multicast);
        udp.Send(Encoding.UTF8.GetBytes(p2), p2.Length, Multicast);

        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
            byte[] buffer;
            try
            {
                buffer = udp.Receive(ref remote);
            }
            catch (SocketException ex) when (ex.SocketErrorCode == SocketError.TimedOut)
            {
                continue;
            }
            catch (ObjectDisposedException)
            {
                break;
            }

            string xml;
            try
            {
                xml = Encoding.UTF8.GetString(buffer);
            }
            catch
            {
                continue;
            }

            if (xml.Length < 20 || !xml.Contains("XAddrs", StringComparison.Ordinal))
                continue;

            try
            {
                var doc = XDocument.Parse(xml, LoadOptions.PreserveWhitespace);
                foreach (var el in doc.Descendants())
                {
                    if (!string.Equals(el.Name.LocalName, "XAddrs", StringComparison.OrdinalIgnoreCase))
                        continue;
                    var raw = el.Value.Trim();
                    if (string.IsNullOrEmpty(raw))
                        continue;
                    var addrs = raw.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    if (addrs.Length == 0)
                        continue;
                    if (!seen.Add(addrs[0]))
                        continue;

                    var scopes = doc
                        .Descendants()
                        .FirstOrDefault(x => string.Equals(x.Name.LocalName, "Scopes", StringComparison.OrdinalIgnoreCase));
                    found.Add(
                        new DiscoveredOnvifDevice
                        {
                            Remote = remote,
                            XAddrs = addrs,
                            Scopes = scopes?.Value,
                        });
                }
            }
            catch
            {
                // resposta de outro dispositivo
            }
        }

        return found.AsReadOnly();
    }

    private static string BuildProbe(bool includeNetworkVideo)
    {
        var id = "urn:uuid:" + Guid.NewGuid().ToString("D", System.Globalization.CultureInfo.InvariantCulture);
        var types = includeNetworkVideo
            ? """<d:Types xmlns:dn="http://www.onvif.org/ver10/network/wsdl">dn:NetworkVideoTransmitter</d:Types>"""
            : "";

        return $"""
            <?xml version="1.0" encoding="UTF-8"?>
            <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
                        xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                        xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
              <s:Header>
                <a:MessageID>{id}</a:MessageID>
                <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
                <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
              </s:Header>
              <s:Body>
                <d:Probe>
                  {types}
                </d:Probe>
              </s:Body>
            </s:Envelope>
            """;
    }
}
