// MCP server v C# — proxy nad HTTP API z HW2. Doménu neduplikuje.
//
//   klient --MCP--> tento server --HTTP--> hw2 api --> timeagent.tools
//
// Ostrá varianta je Python server v ../mcp. Viz docs/dva-servery.md.

using ModelContextProtocol.Protocol;
using TimeAgent.Mcp;

var apiBase = Environment.GetEnvironmentVariable("TOOLS_BASE_URL") ?? "http://127.0.0.1:8000";

// Healthcheck kontejneru. V aspnet image není wget ani curl, takže si o zdraví
// řekne sám server: `dotnet TimeAgent.Mcp.dll --healthcheck` vrátí 0 nebo 1.
if (args.Contains("--healthcheck"))
{
    using var probe = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
    try
    {
        var response = await probe.GetAsync("http://localhost:8000/health");
        return response.IsSuccessStatusCode ? 0 : 1;
    }
    catch
    {
        return 1;
    }
}

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddHttpClient<ToolCatalog>(client =>
{
    // Lomítko na konci je nutné, jinak relativní "tools" přepíše poslední segment.
    client.BaseAddress = new Uri(apiBase.TrimEnd('/') + "/");
    client.Timeout = TimeSpan.FromSeconds(30);
});

builder.Services.AddMcpServer(options =>
{
    options.ServerInfo = new Implementation { Name = "timeagent-dotnet", Version = "0.1.0" };
    options.ServerInstructions =
        "Nástroje nad databází výkazů odpracovaného času a fakturačních podkladů. "
        + "Čísla ber vždy z nástrojů, nikdy je nedopočítávej.";
})
    .WithHttpTransport()
    // Handlery, ne [McpServerTool]: nástroje nejsou známé při překladu,
    // schémata přijdou za běhu z API.
    .WithListToolsHandler(async (context, ct) =>
    {
        var catalog = context.Services!.GetRequiredService<ToolCatalog>();
        return new ListToolsResult { Tools = await catalog.GetToolsAsync(ct) };
    })
    .WithCallToolHandler(async (context, ct) =>
    {
        var catalog = context.Services!.GetRequiredService<ToolCatalog>();
        return await catalog.CallAsync(context.Params!.Name, context.Params.Arguments, ct);
    });

var app = builder.Build();

// Zdraví = dosažitelnost upstreamu; bez něj server neumí nic.
app.MapGet("/health", async (ToolCatalog catalog, CancellationToken ct) =>
{
    try
    {
        var tools = await catalog.GetToolsAsync(ct);
        return Results.Ok(new { status = "ok", upstream = apiBase, tools = tools.Count });
    }
    catch (Exception exc)
    {
        return Results.Json(
            new
            {
                status = "nedostupné",
                upstream = apiBase,
                error = $"{exc.GetType().Name}: {exc.Message}",
                hint = "Běží HTTP API z HW2? `cd HW2 && docker compose up -d api`",
            },
            statusCode: 503);
    }
});

app.MapMcp("/mcp");

app.Run();
return 0;

// Kvůli WebApplicationFactory v testech.
public partial class Program;
