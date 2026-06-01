using System.Text.Json;
using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Commands;
using CounterStrikeSharp.API.Modules.Timers;

namespace CS2WebUI.Bridge;

public sealed class CS2WebUIBridge : BasePlugin
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };
    public override string ModuleName => "CS2 WebUI Bridge";
    public override string ModuleVersion => "0.1.0";
    public override string ModuleAuthor => "CS2 WebUI contributors";
    public override string ModuleDescription => "Structured CS2 player and match snapshots for CS2 WebUI.";

    private string StateDirectory => Path.Combine(ModuleDirectory, "state");

    public override void Load(bool hotReload)
    {
        Directory.CreateDirectory(StateDirectory);
        AddCommand("css_webui_snapshot", "Write a CS2 WebUI player snapshot.", SnapshotCommand);
        RegisterEventHandler<EventCsWinPanelMatch>(OnMatchFinished);
        RegisterEventHandler<EventPlayerConnectFull>(OnPlayersChanged);
        RegisterEventHandler<EventPlayerDisconnect>(OnPlayersChanged);
        RegisterEventHandler<EventPlayerDeath>(OnPlayersChanged);
        AddTimer(30.0f, WritePlayers, TimerFlags.REPEAT);
        WritePlayers();
    }

    private void SnapshotCommand(CCSPlayerController? caller, CommandInfo command)
    {
        WritePlayers();
        command.ReplyToCommand("CS2 WebUI player snapshot updated.");
    }

    private HookResult OnMatchFinished(EventCsWinPanelMatch gameEvent, GameEventInfo info)
    {
        WritePlayers();
        WriteJson("match-ended.json", new MatchEnded(DateTimeOffset.UtcNow));
        return HookResult.Continue;
    }

    private HookResult OnPlayersChanged<T>(T gameEvent, GameEventInfo info)
        where T : GameEvent
    {
        Server.NextFrame(WritePlayers);
        return HookResult.Continue;
    }

    private void WritePlayers()
    {
        var players = Utilities
            .GetPlayers()
            .Where(player => player.IsValid)
            .Select(player => new PlayerSnapshot(
                player.PlayerName,
                player.SteamID,
                player.IsBot,
                player.TeamNum,
                player.Score))
            .ToArray();
        WriteJson("players.json", players);
    }

    private void WriteJson<T>(string name, T value)
    {
        var target = Path.Combine(StateDirectory, name);
        var temporary = target + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(value, JsonOptions));
        File.Move(temporary, target, true);
    }

    private sealed record PlayerSnapshot(
        string Name,
        ulong SteamId64,
        bool IsBot,
        byte Team,
        int Score);

    private sealed record MatchEnded(DateTimeOffset FinishedAt);
}
