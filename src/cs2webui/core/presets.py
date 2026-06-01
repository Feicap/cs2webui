"""Built-in server presets and reusable quick commands."""

PRESETS = {
    "competitive": {
        "label": "Competitive",
        "version": "2026.05",
        "commands": ["game_type 0", "game_mode 1", "exec server.cfg"],
    },
    "casual": {
        "label": "Casual",
        "version": "2026.05",
        "commands": ["game_type 0", "game_mode 0", "exec server.cfg"],
    },
    "deathmatch": {
        "label": "Deathmatch",
        "version": "2026.05",
        "commands": ["game_type 1", "game_mode 2", "exec server.cfg"],
    },
    "workshop": {
        "label": "Workshop",
        "version": "2026.05",
        "commands": ["exec server.cfg"],
    },
    "custom": {
        "label": "Custom",
        "version": "2026.05",
        "commands": ["exec server.cfg"],
    },
}

QUICK_COMMANDS = [
    {
        "id": "restart-game",
        "label": "Restart game",
        "command": "mp_restartgame {seconds}",
        "parameters": [{"name": "seconds", "type": "integer", "default": 1}],
    },
    {
        "id": "bot-quota",
        "label": "Bot quota",
        "command": "bot_quota {count}",
        "parameters": [{"name": "count", "type": "integer", "default": 0}],
    },
    {
        "id": "add-bot",
        "label": "Add bot",
        "command": "bot_add",
        "parameters": [],
    },
    {
        "id": "change-map",
        "label": "Change map",
        "command": "changelevel {map}",
        "parameters": [{"name": "map", "type": "string", "default": "de_dust2"}],
    },
]
