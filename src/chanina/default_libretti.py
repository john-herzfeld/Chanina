"""
Default libretti with internal purposes, registered on every
ChaninaApplication instance at instantiation time.
"""
import logging


def build_default_libretti(app) -> None:
    """
    Register the built-in libretti on ``app``.

    The ``'chanina.*'`` prefix is reserved for these internal tasks; user
    libretti should not be registered under it.
    """
    def chanina_new_page(*args, **_):
        """
        Open a new page on the injected session, mostly useful to
        sanity-check that the shared browser is reachable.
        """
        session = args[0] if args else None
        if session is None:
            return
        try:
            session.new_page()
        except Exception as e:
            logging.error(f"[ChaninaDefaultFeature] Failed to open a new page: {e}")

    def chanina_list_libretti(*_, **__):
        """ Log the dictionary of the currently registered libretti. """
        logging.info(f"[ChaninaDefaultFeature] chanina.list_libretti: {app.libretti}")

    app.libretto("chanina.list_libretti")(chanina_list_libretti)
    app.libretto("chanina.new_page")(chanina_new_page)
