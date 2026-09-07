using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using ModelContextProtocol.Client;
using TimeAgent.Mcp;

namespace TimeAgent.Mcp.Tests;

/// <summary>Testy překladu HTTP → MCP. Upstream je podvržený, Docker není potřeba.</summary>
public sealed class ProxyGuaranteesTests
{
    private static async Task<McpClient> ConnectAsync(WebApplicationFactory<Program> factory)
    {
        // HttpClient testovacího serveru — MCP jde v paměti, bez portu.
        var transport = new HttpClientTransport(
            new HttpClientTransportOptions
            {
                Name = "test",
                Endpoint = new Uri("http://localhost/mcp"),
                TransportMode = HttpTransportMode.StreamableHttp,
            },
            factory.CreateClient());

        return await McpClient.CreateAsync(transport);
    }

    private static WebApplicationFactory<Program> Factory(StubUpstream upstream) =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureTestServices(services =>
                services.AddHttpClient<ToolCatalog>(c => c.BaseAddress = new Uri("http://stub/"))
                        .ConfigurePrimaryHttpMessageHandler(() => upstream)));

    private static JsonElement Payload(ModelContextProtocol.Protocol.CallToolResult result)
    {
        var text = ((ModelContextProtocol.Protocol.TextContentBlock)result.Content[0]).Text;
        return JsonSerializer.Deserialize<JsonElement>(text);
    }

    [Fact]
    public async Task Schemata_se_prebiraji_z_HW1_doslova()
    {
        using var factory = Factory(new StubUpstream());
        await using var client = await ConnectAsync(factory);

        var tools = await client.ListToolsAsync();

        Assert.Equal(["capacity_check", "compute_invoice"], tools.Select(t => t.Name).Order());
        var capacity = tools.Single(t => t.Name == "capacity_check");
        Assert.Equal(StubUpstream.CapacityDescription, capacity.Description);
        Assert.Equal(
            "Měsíc ve formátu YYYY-MM",
            capacity.JsonSchema.GetProperty("properties").GetProperty("month")
                    .GetProperty("description").GetString());
    }

    [Fact]
    public async Task Chyba_prijde_jako_data_a_ne_jako_selhani()
    {
        using var factory = Factory(new StubUpstream());
        await using var client = await ConnectAsync(factory);

        var result = await client.CallToolAsync(
            "compute_invoice",
            new Dictionary<string, object?> { ["project"] = "Neexistující", ["month"] = "2026-08" });

        Assert.NotEqual(true, result.IsError);
        Assert.Contains("Dostupné", Payload(result).GetProperty("error").GetString());
    }

    [Fact]
    public async Task Note_prezije_cestu_proxy()
    {
        using var factory = Factory(new StubUpstream());
        await using var client = await ConnectAsync(factory);

        var result = await client.CallToolAsync(
            "capacity_check", new Dictionary<string, object?> { ["month"] = "2026-11" });

        var payload = Payload(result);
        Assert.Equal(0, payload.GetProperty("total_hours").GetDouble());
        Assert.Contains("Neodhaduj chybějící hodnoty", payload.GetProperty("note").GetString());
    }

    [Fact]
    public async Task Vypadek_upstreamu_taky_jde_jako_data()
    {
        using var factory = Factory(new StubUpstream { FailCalls = true });
        await using var client = await ConnectAsync(factory);

        var result = await client.CallToolAsync(
            "capacity_check", new Dictionary<string, object?> { ["month"] = "2026-08" });

        Assert.NotEqual(true, result.IsError);
        Assert.Contains("nedosáhl na API HW2", Payload(result).GetProperty("error").GetString());
    }

    [Fact]
    public async Task Argumenty_se_preposilaji_beze_zmeny()
    {
        // Narovnání typů dělá HW1; proxy do argumentů nesmí sahat.
        var upstream = new StubUpstream();
        using var factory = Factory(upstream);
        await using var client = await ConnectAsync(factory);

        await client.CallToolAsync(
            "capacity_check",
            new Dictionary<string, object?> { ["month"] = "2026-08", ["target_hours"] = "160" });

        Assert.Equal("""{"month":"2026-08","target_hours":"160"}""", upstream.LastBody);
    }

    [Fact]
    public async Task Health_hlasi_nedostupny_upstream()
    {
        using var factory = Factory(new StubUpstream { FailTools = true });
        using var http = factory.CreateClient();

        var response = await http.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("nedostupné", body.GetProperty("status").GetString());
    }
}

/// <summary>Podvržené API — tvar odpovědí podle HW2/api/main.py.</summary>
internal sealed class StubUpstream : HttpMessageHandler
{
    public const string CapacityDescription =
        "Přehled celého měsíce přes všechny projekty: odpracované hodiny celkem, "
        + "rozdíl proti cíli a plnění v procentech.";

    public bool FailTools { get; init; }
    public bool FailCalls { get; init; }
    public string? LastBody { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;

        if (path.EndsWith("/tools", StringComparison.Ordinal))
        {
            return FailTools
                ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                : Json(ToolsCatalogue.Replace("__POPIS__", CapacityDescription));
        }

        LastBody = request.Content is null
            ? null
            : await request.Content.ReadAsStringAsync(cancellationToken);

        if (FailCalls)
        {
            return new HttpResponseMessage(HttpStatusCode.BadGateway)
            {
                Content = new StringContent("upstream je dole"),
            };
        }

        if (path.EndsWith("/compute_invoice", StringComparison.Ordinal))
        {
            return Json("""
                {"error": "Projekt 'Neexistující' neexistuje. Dostupné: ACME (Acme Corp), INIT (Initech)"}
                """);
        }

        var month = LastBody is not null && LastBody.Contains("2026-11", StringComparison.Ordinal);
        return Json(month ? EmptyMonth : FullMonth);
    }

    // Na jednom řádku: zalomení uvnitř řetězcové hodnoty je neplatný JSON.
    private const string EmptyMonth =
        """{"month": "2026-11", "total_hours": 0, "days_worked": 0, "note": "Za zadané období nejsou v databázi žádné záznamy. Data jsou k dispozici od 2025-01-01 do 2026-09-04. Neodhaduj chybějící hodnoty — odpověz, že za dané období záznamy nejsou."}""";

    private const string FullMonth =
        """{"month": "2026-08", "total_hours": 142.0, "days_worked": 18}""";

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };

    // Placeholder místo interpolace: JSON končí `}}}` a raw interpolovaný
    // literál by kvůli tomu potřeboval `$$$`.
    private const string ToolsCatalogue = """
        {"count": 2, "tools": [
          {"type": "function", "function": {
             "name": "capacity_check",
             "description": "__POPIS__",
             "parameters": {"type": "object",
               "properties": {
                 "month": {"type": "string", "description": "Měsíc ve formátu YYYY-MM"},
                 "target_hours": {"type": "number", "description": "Cílový počet hodin, výchozí 160"}},
               "required": ["month"]}}},
          {"type": "function", "function": {
             "name": "compute_invoice",
             "description": "Fakturační podklad za jeden projekt a měsíc.",
             "parameters": {"type": "object",
               "properties": {
                 "project": {"type": "string", "description": "Projekt"},
                 "month": {"type": "string", "description": "Měsíc ve formátu YYYY-MM"}},
               "required": ["project", "month"]}}}
        ]}
        """;
}
