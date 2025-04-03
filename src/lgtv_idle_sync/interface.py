import logging
import weakref

logger = logging.getLogger(__name__)

class InhibitorToken:
    def __init__(self, idle_manager):
        self._idle_manager = weakref.ref(idle_manager)
        self._finalizer = weakref.finalize(self, self.destroy)

    def destroy(self):
        idle_manager = self._idle_manager()
        if idle_manager:
            idle_manager._uninhibit(self)

class IdleManager:
    def __init__(self):
        self._inhibitors = weakref.WeakSet()

    def _on_resume(self):
        raise NotImplementedError()

    def _on_idle(self):
        raise NotImplementedError()

    def _on_inhibit(self):
        raise NotImplementedError()

    def _on_uninhibit(self):
        raise NotImplementedError()

    def resumed(self, *args, **kwargs):
        "Resume from ilding"
        logger.debug("Resuming")
        self._on_resume()

    def idled(self, *args, **kwargs):
        "Start idling"
        if not self._has_inhibitor():
            logger.debug("Idling")
            self._on_idle()

    def _has_inhibitor(self):
        return len(self._inhibitors) > 0

    def inhibit(self):
        """Prevent idling until InhibitToken is destroyed"""
        logger.debug("Inhibiting")
        if not self._has_inhibitor():
            self._on_inhibit()
        inhibitor = InhibitorToken(self)
        self._inhibitors.add(inhibitor)
        return inhibitor

    def _uninhibit(self, inhibitor):
        logger.debug("Uninhibiting")
        self._inhibitors.discard(inhibitor)
        if not self._has_inhibitor():
            self._on_uninhibit()

class Inhibitor:
    def __init__(self, idle_manager):
        self._idle_manager = idle_manager
        self._inhibitor = None

    def _has_inhibitor(self):
        return self._inhibitor is not None

    def inhibit(self):
        if not self._has_inhibitor():
            self._inhibitor = self._idle_manager.inhibit()

    def uninhibit(self):
        if self._has_inhibitor():
            self._inhibitor.destroy()
            self._inhibitor = None
