from nexustiles import NexusTileService

class NexusTileServiceFactory:
    def __init__(self, **kwarg):
        self.__kwargs = kwarg

    def get_service(self):
        return NexusTileService(**self.__kwargs)

