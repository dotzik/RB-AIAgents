using System.Net.Http.Json;
using System.Text.Json;
using ModelContextProtocol.Protocol;

namespace TimeAgent.Mcp;

/// <summary>Nástroje načtené za běhu z HTTP API HW2 a přeložené do MCP tvaru.</summary>
public sealed class ToolCatalog(HttpClient http, ILogger<ToolCatalog> logger)
{
    // Seznam se mění jen s novou verzí HW1. Cache se drží do restartu.
    private IList<Tool>? _cached;
    private readonly SemaphoreSlim _lock = new(1, 1);

    public async Task<IList<Tool>> GetToolsAsync(CancellationToken ct)
    {
        if (_cached is not null)
        {
            return _cached;
        }

        await _lock.WaitAsync(ct);
        try
        {
            return _cached ??= await FetchToolsAsync(ct);
        }
        finally
        {
            _lock.Release();
        }
    }

    private async Task<IList<Tool>> FetchToolsAsync(CancellationToken ct)
    {
        var payload = await http.GetFromJsonAsync<JsonElement>("tools", ct);
        var tools = new List<Tool>();

        foreach (var entry in payload.GetProperty("tools").EnumerateArray())
        {
            var fn = entry.GetProperty("function");
            tools.Add(new Tool
            {
                Name = fn.GetProperty("name").GetString()!,
                Description = fn.GetProperty("description").GetString(),
                // Clone() je nutný — bez něj JsonElement zmizí s dokumentem.
                InputSchema = fn.GetProperty("parameters").Clone(),
            });
        }

        logger.LogInformation("Načteno {Count} nástrojů z {Base}", tools.Count, http.BaseAddress);
        return tools;
    }

    /// <summary>Přepošle volání na API a výsledek vrátí beze změny.</summary>
    /// <remarks>
    /// <c>IsError</c> se nenastavuje ani pro <c>{"error": ...}</c> — model má
    /// hlášku dostat jako obsah a opravit argumenty. S <c>IsError = true</c>
    /// klient běh utne. Neopravovat.
    /// </remarks>
    public async Task<CallToolResult> CallAsync(
        string name, IDictionary<string, JsonElement>? arguments, CancellationToken ct)
    {
        // Neznámý nástroj se nekontroluje tady — HW1 na něj odpoví hláškou
        // se seznamem dostupných, podle které se model umí opravit.
        var response = await http.PostAsJsonAsync(
            $"tools/{Uri.EscapeDataString(name)}",
            arguments ?? new Dictionary<string, JsonElement>(),
            ct);

        JsonElement payload;
        if (response.IsSuccessStatusCode)
        {
            payload = await response.Content.ReadFromJsonAsync<JsonElement>(ct);
        }
        else
        {
            // Nedostupné API taky jako data, ne jako protokolová chyba.
            var body = await response.Content.ReadAsStringAsync(ct);
            logger.LogWarning("Nástroj {Name}: API vrátilo {Status}", name, (int)response.StatusCode);
            payload = JsonSerializer.SerializeToElement(new Dictionary<string, string>
            {
                ["error"] = $"Nástroj {name} nedosáhl na API HW2 (HTTP {(int)response.StatusCode}). "
                            + body[..Math.Min(body.Length, 200)],
            });
        }

        return new CallToolResult
        {
            Content = [new TextContentBlock { Text = JsonSerializer.Serialize(payload, JsonOptions) }],
            StructuredContent = payload,
        };
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        // Bez toho jde čeština v hláškách do \uXXXX.
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = true,
    };
}
