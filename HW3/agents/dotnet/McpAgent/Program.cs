// Agent nad MCP serverem, na Microsoft Agent Framework (Microsoft.Agents.AI).
//
// Nástroje přijdou ze serveru přes ListToolsAsync; McpClientTool dědí z
// AIFunction, takže jdou do ChatClientAgent bez adaptéru. Smyčku nad nimi
// i systémové instrukce drží agent sám.
//
//   dotnet run -- ask "Kolik hodin jsem odpracoval v srpnu 2026?" [--json]
//   dotnet run -- tools

using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using ModelContextProtocol.Client;
using OllamaSharp;

const string DefaultMcpUrl = "http://127.0.0.1:8010/mcp";
const string DefaultOllamaUrl = "http://127.0.0.1:11434";
const string DefaultModel = "qwen2.5:32b";

// Jinak Windows vypíše otazníky místo diakritiky.
Console.OutputEncoding = Encoding.UTF8;

// Bez toho jde čeština do \uXXXX.
var jsonOpts = new JsonSerializerOptions
{
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
};

// Adresa modelu a serveru z HW3/.env — stejný zdroj jako pro Python klienta.
LoadDotEnv();

var cmd = args.Length > 0 ? args[0] : "";
if (cmd is not ("ask" or "tools"))
{
    Console.Error.WriteLine("Použití: McpAgent ask \"otázka\" [--json] | McpAgent tools");
    return 2;
}

var options = ParseOptions(args);
var mcpUrl = options.GetValueOrDefault("--mcp-url")
             ?? Environment.GetEnvironmentVariable("MCP_URL") ?? DefaultMcpUrl;
var ollamaUrl = options.GetValueOrDefault("--ollama-url")
                ?? Environment.GetEnvironmentVariable("OLLAMA_BASE_URL") ?? DefaultOllamaUrl;
var model = options.GetValueOrDefault("--model")
            ?? Environment.GetEnvironmentVariable("OLLAMA_MODEL") ?? DefaultModel;
var asJson = args.Contains("--json");

// Natvrdo, ne AutoDetect — server umí jen Streamable HTTP a autodetekce
// by při každém běhu zkoušela i SSE.
await using var mcpClient = await McpClient.CreateAsync(
    new HttpClientTransport(new HttpClientTransportOptions
    {
        Name = "timeagent",
        Endpoint = new Uri(mcpUrl),
        TransportMode = HttpTransportMode.StreamableHttp,
    }));

var tools = await mcpClient.ListToolsAsync();

if (cmd == "tools")
{
    foreach (var t in tools)
    {
        Console.WriteLine(t.Name);
        Console.WriteLine("    " + (t.Description ?? "").Split('\n')[0]);
    }
    return 0;
}

var question = args.Skip(1).FirstOrDefault(a => !a.StartsWith("--"));
if (string.IsNullOrWhiteSpace(question))
{
    Console.Error.WriteLine("Chybí otázka.");
    return 2;
}

// OllamaSharp jde po nativní /api/chat; na starší cestě novější modely
// tool call tiše zahodí a vrátí prázdnou odpověď.
IChatClient chat = new OllamaApiClient(new Uri(ollamaUrl), model);

// ChatClientAgent obstará smyčku nad nástroji i vložení instrukcí,
// takže UseFunctionInvocation() ani ruční ChatMessage seznam nejsou potřeba.
AIAgent agent = new ChatClientAgent(
    chat,
    instructions: BuildSystemPrompt(),
    name: "vykazy",
    description: "Agent nad výkazy odpracovaného času",
    tools: [.. tools]);

var stopwatch = Stopwatch.StartNew();
AgentResponse response;
try
{
    response = await agent.RunAsync(question!);
}
catch (Exception exc)
{
    var message = $"{exc.GetType().Name}: {exc.Message}";
    if (asJson)
        Console.WriteLine(JsonSerializer.Serialize(new { error = message }, jsonOpts));
    else
        Console.Error.WriteLine("Chyba: " + message);
    return 1;
}
stopwatch.Stop();

var calls = response.Messages
    .SelectMany(m => m.Contents)
    .OfType<FunctionCallContent>()
    .Select(c => new ToolCall(c.Name, c.Arguments))
    .ToList();

if (asJson)
{
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        client = "dotnet/microsoft-agent-framework",
        model,
        question,
        answer = response.Text,
        tool_calls = calls,
        tool_call_count = calls.Count,
        seconds = Math.Round(stopwatch.Elapsed.TotalSeconds, 2),
    }, jsonOpts));
}
else
{
    foreach (var call in calls)
        Console.Error.WriteLine($"  → {call.Name}({JsonSerializer.Serialize(call.Arguments, jsonOpts)})");
    Console.WriteLine(response.Text);
}
return 0;

// Vlastní čtenář `.env` místo balíčku, kvůli třem klíčům.
// Hledá se nahoru od binárky — funguje z `dotnet run` i z publish výstupu.
static void LoadDotEnv()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir is not null && !File.Exists(Path.Combine(dir.FullName, ".env")))
        dir = dir.Parent;
    if (dir is null)
        return;

    foreach (var line in File.ReadAllLines(Path.Combine(dir.FullName, ".env")))
    {
        var trimmed = line.Trim();
        if (trimmed.Length == 0 || trimmed[0] == '#')
            continue;
        var eq = trimmed.IndexOf('=');
        if (eq <= 0)
            continue;
        var key = trimmed[..eq].Trim();
        // Prostředí má přednost před souborem.
        if (Environment.GetEnvironmentVariable(key) is null)
            Environment.SetEnvironmentVariable(key, trimmed[(eq + 1)..].Trim());
    }
}

static Dictionary<string, string> ParseOptions(string[] args)
{
    var result = new Dictionary<string, string>();
    for (var i = 0; i < args.Length - 1; i++)
        if (args[i].StartsWith("--") && !args[i + 1].StartsWith("--"))
            result[args[i]] = args[i + 1];
    return result;
}

// Prompt pochází z HW1. Soubor generuje `scripts/export_system_prompt.py`,
// ruční editace se ztratí.
static string BuildSystemPrompt()
{
    var path = Path.Combine(AppContext.BaseDirectory, "system_prompt.json");
    var doc = JsonNode.Parse(File.ReadAllText(path))!.AsObject();
    var template = doc["template"]!.GetValue<string>();
    var weekdays = doc["weekdays"]!.AsArray().Select(n => n!.GetValue<string>()).ToArray();

    var today = DateTime.Today;
    // DayOfWeek začíná nedělí; Python má pondělí jako 0.
    var weekdayIndex = ((int)today.DayOfWeek + 6) % 7;
    return template
        .Replace("{today}", today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture))
        .Replace("{weekday}", weekdays[weekdayIndex])
        .Replace("{month}", today.ToString("yyyy-MM", CultureInfo.InvariantCulture));
}

internal record ToolCall(string Name, IDictionary<string, object?>? Arguments);
