# src/ava/core/managers/event_coordinator.py
import asyncio
from src.ava.core.event_bus import EventBus
from src.ava.core.managers.service_manager import ServiceManager
from src.ava.core.managers.window_manager import WindowManager
from src.ava.core.managers.task_manager import TaskManager
from src.ava.core.managers.workflow_manager import WorkflowManager


class EventCoordinator:
    """
    Coordinates events between different components of the application.
    Single responsibility: Event routing and component integration.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.service_manager: ServiceManager = None
        self.window_manager: WindowManager = None
        self.task_manager: TaskManager = None
        self.workflow_manager: WorkflowManager = None
        print("[EventCoordinator] Initialized")

    def set_managers(self, service_manager: ServiceManager, window_manager: WindowManager, task_manager: TaskManager, workflow_manager: WorkflowManager):
        """Set references to other managers."""
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.workflow_manager = workflow_manager

        # Pass managers to the action service now that they are all available
        action_service = self.service_manager.get_action_service()
        if action_service:
            action_service.window_manager = self.window_manager
            action_service.task_manager = self.task_manager


    def wire_all_events(self):
        """Wire all events between components."""
        print("[EventCoordinator] Wiring all events...")
        self._wire_ui_events()
        self._wire_ai_workflow_events()
        self._wire_execution_events()
        self._wire_terminal_events()
        self._wire_plugin_events()
        self._wire_chat_session_events()
        # --- THIS IS THE FIX ---
        # Removed the '✓' character to prevent encoding errors on Windows
        print("[EventCoordinator] All events wired successfully.")
        # --- END OF FIX ---

    def _wire_chat_session_events(self):
        """Wire events for saving and loading chat sessions."""
        if not self.window_manager: return
        chat_interface = self.window_manager.get_main_window().chat_interface
        if chat_interface:
            self.event_bus.subscribe("save_chat_requested", chat_interface.save_session)
            self.event_bus.subscribe("load_chat_requested", chat_interface.load_session)
            print("[EventCoordinator] Chat session events wired.")

    def _wire_ui_events(self):
        if not all([self.service_manager, self.window_manager]):
            return

        action_service = self.service_manager.get_action_service()
        if action_service:
            self.event_bus.subscribe("new_project_requested", action_service.handle_new_project)
            self.event_bus.subscribe("load_project_requested", action_service.handle_load_project)
            self.event_bus.subscribe("new_session_requested", action_service.handle_new_session)

        app_state_service = self.service_manager.get_app_state_service()
        if app_state_service:
            self.event_bus.subscribe("interaction_mode_change_requested", app_state_service.set_interaction_mode)

        if self.window_manager:
            self.event_bus.subscribe("app_state_changed", self.window_manager.handle_app_state_change)

        self.event_bus.subscribe(
            "configure_models_requested",
            lambda: asyncio.create_task(self.window_manager.show_model_config_dialog())
        )
        rag_manager = self.service_manager.get_rag_manager()
        if rag_manager:
            self.event_bus.subscribe("scan_directory_requested", rag_manager.open_scan_directory_dialog)
            self.event_bus.subscribe("add_active_project_to_rag_requested", rag_manager.ingest_active_project)
        self.event_bus.subscribe("plugin_management_requested", self.window_manager.show_plugin_management_dialog)
        plugin_manager = self.service_manager.get_plugin_manager()
        if plugin_manager:
            self.event_bus.subscribe("plugin_enable_requested",
                                     lambda name: asyncio.create_task(plugin_manager.start_plugin(name)))
            self.event_bus.subscribe("plugin_disable_requested",
                                     lambda name: asyncio.create_task(plugin_manager.stop_plugin(name)))
            self.event_bus.subscribe("plugin_reload_requested",
                                     lambda name: asyncio.create_task(plugin_manager.reload_plugin(name)))
        self.event_bus.subscribe("show_log_viewer_requested", self.window_manager.show_log_viewer)
        self.event_bus.subscribe("show_code_viewer_requested", self.window_manager.show_code_viewer)
        print("[EventCoordinator] UI events wired.")

    def _wire_ai_workflow_events(self):
        if self.workflow_manager:
            self.event_bus.subscribe("user_request_submitted", self.workflow_manager.handle_user_request)
            self.event_bus.subscribe("review_and_fix_requested", self.workflow_manager.handle_review_and_fix_button)
            self.event_bus.subscribe("fix_highlighted_error_requested",
                                     self.workflow_manager.handle_highlighted_error_fix_request)
        code_viewer = self.window_manager.get_code_viewer()
        if code_viewer:
            self.event_bus.subscribe("prepare_for_generation", code_viewer.prepare_for_generation)
            self.event_bus.subscribe("stream_code_chunk", code_viewer.stream_code_chunk)
            self.event_bus.subscribe("code_generation_complete", code_viewer.display_code)
        print("[EventCoordinator] AI workflow events wired.")

    def _wire_execution_events(self):
        code_viewer = self.window_manager.get_code_viewer()
        if code_viewer:
            self.event_bus.subscribe("error_highlight_requested", code_viewer.highlight_error_in_editor)
            self.event_bus.subscribe("clear_error_highlights", code_viewer.clear_all_error_highlights)
        if self.workflow_manager:
            self.event_bus.subscribe("execution_failed", self.workflow_manager.handle_execution_failed)
        print("[EventCoordinator] Execution events wired.")

    def _wire_terminal_events(self):
        if not (self.task_manager and self.service_manager): return
        self.event_bus.subscribe("terminal_command_entered", self._handle_terminal_command)
        print("[EventCoordinator] Terminal events wired.")

    def _handle_terminal_command(self, command: str, session_id: int):
        terminal_service = self.service_manager.get_terminal_service()
        if not terminal_service: return
        command_coroutine = terminal_service.execute_command(command, session_id)
        self.task_manager.start_terminal_command_task(command_coroutine, session_id)

    def _wire_plugin_events(self):
        plugin_manager = self.service_manager.get_plugin_manager()
        if plugin_manager:
            self.event_bus.subscribe("plugin_loaded", lambda name: print(f"[EventCoordinator] Plugin loaded: {name}"))
            self.event_bus.subscribe("plugin_unloaded", lambda name: print(f"[EventCoordinator] Plugin unloaded: {name}"))
            self.event_bus.subscribe("plugin_error", lambda name, err: self.event_bus.emit("log_message_received", "Plugin", "error", f"Error in {name}: {err}"))
            self.event_bus.subscribe("plugin_state_changed", self._on_plugin_state_changed_for_sidebar)
        print("[EventCoordinator] Plugin events wired.")

    def _on_plugin_state_changed_for_sidebar(self, plugin_name, old_state, new_state):
        self._update_sidebar_plugin_status()

    def _update_sidebar_plugin_status(self):
        if not self.service_manager or not self.window_manager: return
        plugin_manager = self.service_manager.get_plugin_manager()
        if not plugin_manager: return
        enabled_plugins = plugin_manager.config.get_enabled_plugins()
        status = "off"
        if enabled_plugins:
            all_plugins_info = plugin_manager.get_all_plugins_info()
            status = "ok"
            for plugin in all_plugins_info:
                if plugin['name'] in enabled_plugins and plugin.get('state') != 'started':
                    status = "error"
                    break
        main_window = self.window_manager.get_main_window()
        if main_window and hasattr(main_window, 'sidebar'):
            main_window.sidebar.update_plugin_status(status)
            print(f"[EventCoordinator] Sidebar plugin status updated to: {status}")