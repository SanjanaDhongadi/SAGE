import logging

class EventBus:
    def __init__(self):
        self._listeners = {}

    def subscribe(self, event_type: str, callback):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    def publish(self, event_type: str, data: dict):
        listeners = self._listeners.get(event_type, [])
        # Also support catch-all listeners
        all_listeners = self._listeners.get("*", [])
        
        for callback in listeners + all_listeners:
            try:
                callback(event_type, data)
            except Exception as e:
                logging.error(f"[EventBus] Error in listener for {event_type}: {e}")

# Global bus instance
bus = EventBus()
