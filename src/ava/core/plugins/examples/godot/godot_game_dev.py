# src/ava/core/plugins/examples/godot/godot_game_dev.py
from src.ava.core.plugins.plugin_system import PluginBase, PluginMetadata

class GodotGameDevPlugin(PluginBase):
    """
    A simple plugin whose only job is to be discovered by the system,
    allowing "Godot" to be a selectable project type. The core logic
    for handling this project type is now in the WorkflowManager.
    """
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Godot Game Dev",
            version="1.1.0",
            description="Enables Avakin to generate Godot game files (GDScript, scenes).",
            author="Avakin",
            enabled_by_default=True
        )

    async def load(self) -> bool:
        self.log("info", f"{self.metadata.name} loaded.")
        return True

    async def start(self) -> bool:
        self.log("info", f"{self.metadata.name} started. The WorkflowManager will now handle Godot builds.")
        self.set_state(self.state.STARTED)
        return True

    async def stop(self) -> bool:
        self.log("info", f"{self.metadata.name} stopped.")
        self.set_state(self.state.STOPPED)
        return True

    async def unload(self) -> bool:
        return True